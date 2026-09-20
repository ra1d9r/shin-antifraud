"""Служебные контракты: health, статистика, список транзакций, ошибки."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.enums import Decision, RiskLevel, ScenarioKey, Verdict
from app.schemas.transaction import TransactionRequest


class ModelInfo(BaseModel):
    """Сведения о загруженной модели."""

    loaded: bool
    algorithm: str | None = None
    calibration_method: str | None = None
    feature_count: int | None = None
    trained_at: str | None = None
    format_version: str | None = None
    roc_auc: float | None = None
    pr_auc: float | None = None
    precision: float | None = None
    recall: float | None = None
    f1: float | None = None


class HealthResponse(BaseModel):
    """Проверка работоспособности API (ТЗ §2.1)."""

    status: str = Field(description="ok — система готова; degraded — модель не загружена")
    app_name: str
    version: str
    environment: str
    model_loaded: bool
    explainer_method: str | None = Field(
        default=None, description="Используемый способ расчёта вкладов"
    )
    rules_enabled: bool
    transactions_processed: int
    uptime_seconds: float


class DecisionBreakdown(BaseModel):
    approve: int = 0
    challenge: int = 0
    block: int = 0


class StatsResponse(BaseModel):
    """Статистика по обработанным транзакциям (ТЗ §2.1, §8.1)."""

    total_transactions: int = Field(description="Всего обработано транзакций")
    suspicious_transactions: int = Field(description="Отправлено на проверку (CHALLENGE)")
    blocked_transactions: int = Field(description="Заблокировано (BLOCK)")
    approved_transactions: int = Field(description="Разрешено (APPROVE)")
    average_risk_score: float = Field(description="Средний Risk Score")
    fraud_rate: float = Field(
        description=(
            "Доля транзакций, признанных рискованными: решение отличается от APPROVE. "
            "Это оценка системы, а не проверенная истина: здесь она судит сама себя. "
            "Подтверждённые числа — в GET /feedback/summary, по разметке аналитика."
        )
    )
    decisions: DecisionBreakdown
    risk_levels: dict[str, int] = Field(default_factory=dict)
    total_amount: float = Field(description="Сумма всех обработанных транзакций")
    blocked_amount: float = Field(description="Сумма заблокированных транзакций")
    top_countries: dict[str, int] = Field(default_factory=dict)
    triggered_rules: dict[str, int] = Field(
        default_factory=dict, description="Сколько раз сработала каждая политика"
    )


class TransactionRecordOut(BaseModel):
    """Строка таблицы транзакций (ТЗ §8.2)."""

    transaction_id: str
    user_id: str
    timestamp: datetime
    amount: float
    country: str
    merchant: str
    device_id: str
    risk_score: int
    model_score: int
    decision: Decision
    risk_level: RiskLevel
    triggered_rules: list[str] = Field(default_factory=list)
    top_reason: str | None = None
    ip_subnet: str | None = Field(
        default=None,
        description="Подсеть /24 — по ней строится граф связей. Полный адрес не хранится",
    )
    # Разметка аналитика, если операцию уже разобрали. null — ещё нет.
    # Лежит здесь, а не отдельным запросом: таблица без пометки «уже
    # проверено» заставила бы разбирать одно и то же дважды.
    verdict: Verdict | None = None
    actual_fraud: bool | None = Field(
        default=None, description="Подтверждённая метка: была ли операция мошеннической"
    )


class TransactionListResponse(BaseModel):
    """Постраничный список обработанных транзакций."""

    total: int = Field(description="Сколько записей подошло под фильтры")
    returned: int = Field(description="Сколько записей в этом ответе")
    items: list[TransactionRecordOut]


class ScenarioOut(BaseModel):
    """Готовый сценарий ручного тестирования (ТЗ §9)."""

    key: ScenarioKey
    title: str
    description: str
    expectation: str = Field(description="Какого результата ждём по ТЗ")
    changed_from_normal: list[str] = Field(
        description="Чем сценарий отличается от обычной транзакции"
    )
    transaction: TransactionRequest = Field(description="Готовое тело запроса")


class ScenarioListResponse(BaseModel):
    items: list[ScenarioOut]


class ErrorResponse(BaseModel):
    """Единый формат ошибки."""

    error_code: str
    message: str
    details: dict = Field(default_factory=dict)
