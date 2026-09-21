"""Единый источник конфигурации Shin.

Все настраиваемые величины системы (пороги Risk Score, пути к артефактам,
параметры датасета, стоимости бизнес-ошибок) живут здесь и читаются из `.env`.

Правило проекта: никакой модуль не хардкодит бизнес-константу у себя внутри —
он берёт её из `get_settings()`.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/config/settings.py -> backend/app/config -> backend/app -> backend -> <root>
PROJECT_ROOT: Path = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """Типизированная конфигурация приложения."""

    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        # `model_` — защищённый префикс в pydantic v2; в проекте есть MODEL_PATH.
        protected_namespaces=(),
    )

    # ------------------------------------------------------------------ app
    app_name: str = "Shin Anti-Fraud System"
    app_version: str = "1.0.0"
    environment: str = "development"
    debug: bool = True
    log_level: str = "INFO"

    # ------------------------------------------------------------------ api
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_prefix: str = ""
    cors_origins: str = "http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173"

    # ---------------------------------------------------------- risk engine
    risk_approve_max: int = Field(default=30, ge=0, le=100)
    risk_challenge_max: int = Field(default=70, ge=0, le=100)
    risk_critical_min: int = Field(default=90, ge=0, le=100)

    # --- жёсткие политики поверх ML.
    # Каждое правило задаёт МИНИМАЛЬНЫЙ Risk Score при срабатывании: правила
    # только поднимают оценку модели, но никогда её не снижают.
    rules_enabled: bool = True

    # Адаптивный порог по категории мерчанта (брифинг §6). Выключен
    # по умолчанию: выгруженная аналитика считается на одном пороге
    # для всех операций, и включённый режим разошёлся бы с числами
    # на дашборде. Панель показывает измеренный эффект, а решение
    # включать остаётся за оператором.
    adaptive_thresholds_enabled: bool = False

    # --- LLM-ассистент риск-аналитика (брифинг §6) ---
    #
    # Пишет клиенту, почему у него попросили подтверждение. Решение
    # при этом принимает модель: ассистент только формулирует уже
    # принятое, и без ключа система работает на детерминированном
    # тексте из тех же фактов.
    llm_enabled: bool = True
    # SecretStr, а не str: так ключ не попадёт ни в repr настроек,
    # ни в лог, ни в трассировку исключения. Прочитать его можно
    # только явным `get_secret_value()`.
    llm_api_key: SecretStr = SecretStr("")
    llm_base_url: str = "https://api.deepseek.com"
    llm_model: str = "deepseek-chat"
    # Ответ идёт человеку и ждёт его в интерфейсе, поэтому ожидание
    # короткое: лучше показать запасной текст, чем крутить спиннер.
    llm_timeout_seconds: float = Field(default=12.0, gt=0.0, le=60.0)
    # Путь этого числа: было 220 — казахский обрывался, английский нет.
    # Специфичные казахские буквы редки в словаре токенизатора, и один
    # и тот же смысл стоит там примерно вдвое дороже (по наблюдению —
    # 1.9 символа на токен).
    #
    # Подняли до 400 — обрыв остался. Стало ясно, что дело не в лимите:
    # модель на казахском писала вдвое больше запрошенного, шесть-восемь
    # предложений вместо трёх-четырёх, и уходила за любой потолок.
    # Лечится это в промпте (правило 6), а не здесь.
    #
    # 600 — потолок на случай, если модель всё-таки разговорится.
    # Он почти ничего не стоит: `max_tokens` ограничивает, а не заказывает,
    # и за уложившийся в 250 токенов ответ платится 250. Дороже был бы
    # потолок, за которым начинается стена текста в письме клиенту банка.
    #
    # Обрыв в любом случае не пройдёт незамеченным: `_extract_text`
    # смотрит `finish_reason` и предпочтёт запасной текст обрубку.
    llm_max_tokens: int = Field(default=600, ge=32, le=2000)

    # Пароль на смену порогов в рантайме. Пустая строка — эндпоинт записи
    # выключен, и это умышленно безопасное значение по умолчанию: адрес,
    # которым можно отключить блокировки, без пароля открыт кому угодно,
    # а публичный демонстрационный стенд у проекта есть.
    config_admin_token: str = ""

    rule_impossible_travel_min_score: int = Field(default=75, ge=0, le=100)
    rule_high_risk_country_min_score: int = Field(default=55, ge=0, le=100)
    rule_unusual_country_min_score: int = Field(default=40, ge=0, le=100)
    rule_new_device_min_score: int = Field(default=35, ge=0, le=100)
    rule_velocity_min_score: int = Field(default=60, ge=0, le=100)
    rule_new_account_amount_min_score: int = Field(default=60, ge=0, le=100)

    # Пороги срабатывания правил
    rule_velocity_txn_per_hour: int = Field(default=6, ge=1)
    rule_new_account_amount_ratio: float = Field(default=4.0, gt=0.0)

    # ---------------------------------------------------------- теневой режим
    # Вторая конфигурация на том же потоке: её решения никуда не уходят,
    # считаются только расхождения с основной.
    shadow_enabled: bool = True
    # `None` — наследовать у основной. Теневая конфигурация обычно
    # отличается одним-двумя значениями, и требовать перечислить остальные
    # значило бы завести второе место, где они разъезжаются с основными.
    shadow_approve_max: int | None = Field(default=None, ge=0, le=100)
    shadow_challenge_max: int | None = Field(default=None, ge=0, le=100)
    shadow_critical_min: int | None = Field(default=None, ge=0, le=100)
    # По умолчанию тень проверяет самое неприятное открытие дашборда:
    # четыре политики из шести не ловят ничего сверх модели, а трение
    # добавляют. Тень считает, чего стоило бы их выключить — на живом
    # потоке, а не на обучающем датасете.
    shadow_rules_enabled: bool = False

    # ------------------------------------------------------------------- ml
    model_path: str = "backend/models/fraud_model.joblib"
    metrics_path: str = "backend/models/model_metrics.json"
    # Аналитика по всему датасету: считается скриптом, приложением только читается.
    # Полный проход занимает около двадцати секунд — на старте столько ждать нельзя.
    evaluation_path: str = "backend/models/evaluation.json"
    # Эталонное распределение признаков: с ним сравнивается живой поток.
    # Снимается тем же проходом по датасету, что и аналитика.
    feature_baseline_path: str = "backend/models/feature_baseline.json"
    adaptive_thresholds_path: str = "backend/models/adaptive_thresholds.json"
    dataset_path: str = "backend/data/raw/transactions.csv"

    dataset_rows: int = Field(default=100_000, gt=0)
    dataset_users: int = Field(default=3_000, gt=0)
    dataset_fraud_rate: float = Field(default=0.02, gt=0.0, lt=0.5)
    random_seed: int = 42
    test_size: float = Field(default=0.2, gt=0.0, lt=1.0)

    # ------------------------------------------------------------------ xai
    xai_top_factors: int = Field(default=5, ge=3, le=10)
    xai_use_shap: bool = True

    # -------------------------------------------------------- business cost
    cost_fraud_loss_ratio: float = Field(default=1.0, ge=0.0)
    cost_fraud_fixed: float = Field(default=25.0, ge=0.0)
    cost_false_block: float = Field(default=120.0, ge=0.0)
    cost_false_challenge: float = Field(default=12.0, ge=0.0)

    # -------------------------------------------------------------- storage
    max_stored_transactions: int = Field(default=5_000, gt=0)
    # Разметка аналитика: ручная работа человека, её нельзя терять при
    # перезапуске. Дописывается построчно в JSON Lines.
    feedback_path: str = "backend/data/feedback/labels.jsonl"
    # Идемпотентность POST /predict по transaction_id: повтор получает
    # тот же ответ, а состояние системы не трогается.
    idempotency_enabled: bool = True
    max_idempotency_keys: int = Field(default=5_000, gt=0)

    # ---------------------------------------------------------- validators
    @field_validator("config_admin_token")
    @classmethod
    def _token_is_sendable_in_a_header(cls, value: str) -> str:
        """Пароль уходит в заголовок X-Admin-Token, а заголовки — latin-1.

        Кириллический пароль пройдёт в `.env`, но отправить его не сможет
        ни один клиент: HTTP-заголовки не переносят такие символы. Эндпоинт
        оказался бы настроенным и недоступным одновременно, и разбираться
        пришлось бы по UnicodeEncodeError в чужом коде.
        """
        if value and not value.isascii():
            raise ValueError(
                "CONFIG_ADMIN_TOKEN должен состоять из ASCII-символов: "
                "он передаётся заголовком X-Admin-Token, а HTTP-заголовки "
                "не переносят кириллицу"
            )
        return value

    @field_validator("risk_challenge_max")
    @classmethod
    def _challenge_above_approve(cls, value: int, info) -> int:
        approve_max = info.data.get("risk_approve_max")
        if approve_max is not None and value <= approve_max:
            raise ValueError(
                f"RISK_CHALLENGE_MAX ({value}) должен быть больше "
                f"RISK_APPROVE_MAX ({approve_max})"
            )
        return value

    @field_validator("risk_critical_min")
    @classmethod
    def _critical_above_challenge(cls, value: int, info) -> int:
        challenge_max = info.data.get("risk_challenge_max")
        if challenge_max is not None and value <= challenge_max:
            raise ValueError(
                f"RISK_CRITICAL_MIN ({value}) должен быть больше "
                f"RISK_CHALLENGE_MAX ({challenge_max})"
            )
        return value

    # --------------------------------------------------------- derived data
    @property
    def cors_origins_list(self) -> list[str]:
        """CORS_ORIGINS приходит строкой через запятую — превращаем в список."""
        raw = self.cors_origins.strip()
        if raw == "*":
            return ["*"]
        return [origin.strip() for origin in raw.split(",") if origin.strip()]

    def resolve(self, relative_path: str) -> Path:
        """Путь из конфигурации -> абсолютный путь относительно корня проекта."""
        path = Path(relative_path)
        return path if path.is_absolute() else (PROJECT_ROOT / path).resolve()

    @property
    def model_file(self) -> Path:
        return self.resolve(self.model_path)

    @property
    def metrics_file(self) -> Path:
        return self.resolve(self.metrics_path)

    @property
    def evaluation_file(self) -> Path:
        return self.resolve(self.evaluation_path)

    @property
    def feature_baseline_file(self) -> Path:
        return self.resolve(self.feature_baseline_path)

    @property
    def adaptive_thresholds_file(self) -> Path:
        return self.resolve(self.adaptive_thresholds_path)

    @property
    def dataset_file(self) -> Path:
        return self.resolve(self.dataset_path)

    @property
    def feedback_file(self) -> Path:
        return self.resolve(self.feedback_path)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Кэшированный синглтон настроек (используется как FastAPI-зависимость)."""
    return Settings()


def reload_settings() -> Settings:
    """Сбросить кэш и перечитать `.env` — нужно в тестах."""
    get_settings.cache_clear()
    return get_settings()
