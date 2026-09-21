"""Объяснение решения клиенту (брифинг §6, LLM-ассистент).

Отдельный эндпоинт, а не поле в `POST /predict`, по двум причинам.
Обращение к языковой модели занимает секунды, а предсказание — десятки
миллисекунд, и вешать одно на другое значило бы замедлить каждый вызов
ради текста, который нужен не всем. И второе: без ключа ассистента нет,
а предсказание обязано работать всегда.

Разделение труда описано в `app/assistant/message.py`: решение принимает
модель, языковая модель только формулирует уже принятое.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, status

from app.api.deps import ServiceDep, SettingsDep
from app.assistant import (
    DEFAULT_LANGUAGE,
    LlmClient,
    LlmConfig,
    LlmUnavailableError,
    build_facts,
    contradicts,
    fallback_text,
    needs_assistant,
    system_prompt,
)
from app.core.logging import get_logger
from app.i18n import Language
from app.schemas.assistant import ClientMessage
from app.schemas.system import ErrorResponse
from app.schemas.transaction import TransactionRequest

logger = get_logger("shin.api.assistant")

router = APIRouter(tags=["assistant"])


@router.post(
    "/explain/client",
    response_model=ClientMessage,
    status_code=status.HTTP_200_OK,
    summary="Объяснить решение клиенту человеческим языком",
    description=(
        "Бонус брифинга §6: «LLM-Ассистент Риск-аналитика: генерация "
        "естественного ответа для клиента, объясняющего, почему "
        "потребовалось 2FA-подтверждение».\n\n"
        "**Решение принимает модель, а не ассистент.** Вероятность даёт "
        "обученная модель, оценку и вердикт — Risk Engine, причины — SHAP. "
        "Языковая модель получает готовые факты и только превращает их "
        "во фразу. Выключите её — система продолжит работать так же, "
        "изменится лишь формулировка текста.\n\n"
        "Поле `facts` показывает ровно то, что ушло бы в запрос: "
        "ни идентификатора клиента, ни номера операции, ни IP там нет.\n\n"
        "Поле `source` говорит, кто написал текст. `fallback` означает, "
        "что ответ собран без языковой модели — ключа нет, она не "
        "ответила или её ответ противоречил вердикту системы. Текст "
        "при этом полноценный: он собран из тех же фактов.\n\n"
        "Тело запроса то же, что у `POST /predict`. Состояние системы "
        "не меняется: `persist` игнорируется, как и в отчёте."
    ),
    responses={
        422: {"description": "Некорректные данные транзакции"},
        503: {"model": ErrorResponse, "description": "Модель не загружена"},
    },
)
def explain_for_client(
    request: TransactionRequest,
    service: ServiceDep,
    settings: SettingsDep,
    language: Language = DEFAULT_LANGUAGE,
) -> ClientMessage:
    started = time.perf_counter()

    # Копия без сохранения: объяснение — чтение, а не обработка.
    read_only = request.model_copy(update={"persist": False})
    response = service.predict(read_only, language)
    facts = build_facts(read_only, response)

    text = fallback_text(facts, language)
    source: str = "fallback"
    model: str | None = None
    reason: str | None = None

    if not settings.llm_enabled:
        reason = "Ассистент выключен настройкой LLM_ENABLED."
    elif not needs_assistant(response.decision):
        reason = "Операция одобрена — объяснять клиенту нечего, вызов не нужен."
    else:
        client = LlmClient(LlmConfig.from_settings(settings))
        try:
            generated = client.complete(system_prompt(language), facts.as_prompt_block())
        except LlmUnavailableError as exc:
            reason = exc.message
            logger.info("Ассистент недоступен, показан запасной текст: %s", exc.message)
        else:
            if contradicts(generated, response.decision):
                # Для клиента «отклонена» и «подтвердите» — разные новости,
                # и перепутать их хуже, чем не написать ничего.
                reason = (
                    "Ответ языковой модели противоречил решению системы "
                    f"({response.decision.value}), показан запасной текст."
                )
                logger.warning("Ответ ассистента разошёлся с вердиктом %s", response.decision)
            else:
                text = generated
                source = "llm"
                model = client.model

    return ClientMessage(
        transaction_id=response.transaction_id,
        decision=response.decision,
        text=text,
        source=source,  # type: ignore[arg-type]
        model=model,
        fallback_reason=reason,
        language=language,
        risk_score=response.risk_score,
        facts=facts.as_prompt_block().splitlines(),
        elapsed_ms=round((time.perf_counter() - started) * 1000.0, 1),
    )
