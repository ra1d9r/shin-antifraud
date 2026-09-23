"""Вызов языковой модели (брифинг §6).

Тонкий слой поверх HTTP: собрать запрос, дождаться, вернуть текст или
честно сказать, почему не получилось. Ничего про антифрод здесь нет —
что именно спрашивать, решает `message.py`.

## Про ключ

Ключ приходит настройкой `LLM_API_KEY` и хранится `SecretStr`, поэтому
не появляется ни в `repr` настроек, ни в логе, ни в трассировке. В этом
модуле он читается ровно один раз — при сборке заголовка — и никуда
больше не передаётся.

Ответ об ошибке, который уходит наружу, собирается из кода состояния
и типа исключения, а не из тела ответа провайдера: тело может содержать
эхо запроса, а в запросе есть заголовок авторизации.

## Про совместимость

Используется формат chat completions — тот же у DeepSeek, OpenAI и почти
всех остальных. Поэтому сменить провайдера можно двумя переменными
окружения, не трогая код.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.core.exceptions import ShinError
from app.core.logging import get_logger

logger = get_logger("shin.assistant.llm")


class LlmUnavailableError(ShinError):
    """Языковая модель не ответила. Не поломка системы — повод к запасному тексту."""

    status_code = 503
    error_code = "llm_unavailable"


@dataclass(frozen=True, slots=True)
class LlmConfig:
    """Куда и чем ходить."""

    api_key: str
    base_url: str
    model: str
    timeout_seconds: float
    max_tokens: int

    @property
    def configured(self) -> bool:
        return bool(self.api_key.strip())

    @classmethod
    def from_settings(cls, settings) -> LlmConfig:
        return cls(
            api_key=settings.llm_api_key.get_secret_value(),
            base_url=settings.llm_base_url.rstrip("/"),
            model=settings.llm_model,
            timeout_seconds=settings.llm_timeout_seconds,
            max_tokens=settings.llm_max_tokens,
        )


class LlmClient:
    """Синхронный клиент chat completions."""

    def __init__(self, config: LlmConfig) -> None:
        self._config = config

    @property
    def model(self) -> str:
        return self._config.model

    @property
    def configured(self) -> bool:
        return self._config.configured

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        """Один запрос. Возвращает текст ответа или бросает `LlmUnavailableError`."""
        if not self._config.configured:
            raise LlmUnavailableError(
                "Ключ языковой модели не задан (LLM_API_KEY). "
                "Ответ клиенту собран без неё."
            )

        payload = {
            "model": self._config.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": self._config.max_tokens,
            # Пересказ фактов не место для фантазии: низкая температура
            # уменьшает шанс, что модель добавит своё.
            "temperature": 0.3,
            "stream": False,
        }

        try:
            response = httpx.post(
                f"{self._config.base_url}/chat/completions",
                json=payload,
                headers={
                    "Authorization": f"Bearer {self._config.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=self._config.timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise LlmUnavailableError(
                f"Языковая модель не ответила за {self._config.timeout_seconds:.0f} с"
            ) from exc
        except httpx.HTTPError as exc:
            # Сообщение собирается из типа исключения, а не из текста:
            # текст может содержать URL с параметрами и эхо запроса.
            raise LlmUnavailableError(
                f"Языковая модель недоступна ({type(exc).__name__})"
            ) from exc

        if response.status_code != 200:
            # Тело ответа наружу не уходит намеренно: провайдер вправе
            # вернуть в нём эхо запроса вместе с заголовками.
            raise LlmUnavailableError(
                f"Языковая модель ответила кодом {response.status_code}"
            )

        return _extract_text(response)


def _extract_text(response: httpx.Response) -> str:
    """Достать текст из ответа, не веря его форме.

    Чужой ответ — это данные, а не гарантия. Любое отклонение от
    ожидаемой формы превращается в `LlmUnavailableError`, потому что
    запасной текст лучше, чем `KeyError` в обработчике запроса.
    """
    try:
        body = response.json()
        choice = body["choices"][0]
        text = choice["message"]["content"]
    except Exception as exc:
        raise LlmUnavailableError(
            f"Ответ языковой модели не разобран ({type(exc).__name__})"
        ) from exc

    if not isinstance(text, str) or not text.strip():
        raise LlmUnavailableError("Языковая модель вернула пустой ответ")

    # Обрыв по лимиту токенов. Провайдер отдаёт такой ответ кодом 200
    # и с виду целым — обрыв виден только по `finish_reason`.
    #
    # Оборванный текст показывать нельзя. Он режется на полуслове,
    # и первым исчезает конец — то есть указание, что клиенту делать
    # дальше. Сообщение, которое объяснило задержку и не сказало, как
    # её снять, хуже запасного, который говорит.
    #
    # Обрезать до последнего целого предложения тоже не годится
    # по той же причине: обрезается ровно то, что нужнее всего.
    #
    # Случай не теоретический: на казахском ответ обрывался при лимите,
    # которого русскому и английскому хватало. Специфичные казахские
    # буквы редки в словаре токенизатора, и один и тот же смысл стоит
    # там заметно дороже.
    if choice.get("finish_reason") == "length":
        raise LlmUnavailableError(
            "Ответ языковой модели оборвался на середине: не хватило "
            "лимита токенов (LLM_MAX_TOKENS)."
        )

    return text.strip()
