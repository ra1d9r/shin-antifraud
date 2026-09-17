"""Контракт ответа на анализ транзакции (ТЗ §7).

Ответ намеренно разделяет `model_score` и `risk_score`. Первый — чистый
выход модели, второй — после применения политик Risk Engine. Без этого
разделения нельзя понять, что именно подняло риск, и объяснение решения
получилось бы неполным.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.enums import Decision, ImpactDirection, RiskLevel


class RiskFactorOut(BaseModel):
    """Вклад одного признака в оценку."""

    feature: str = Field(description="Техническое имя признака")
    value: float = Field(description="Значение признака у этой транзакции")
    display_value: str = Field(description="Значение в читаемом виде")
    contribution: float = Field(description="Вклад в оценку; знак задаёт направление")
    direction: ImpactDirection = Field(description="Повышает или понижает риск")
    reason: str = Field(description="Формулировка для человека")
    description: str = Field(description="Описание признака")


class TriggeredRuleOut(BaseModel):
    """Сработавшая политика Risk Engine."""

    key: str = Field(description="Идентификатор политики")
    title: str = Field(description="Формулировка для человека")
    min_score: int = Field(description="Минимальный Risk Score, который задаёт политика")


class ExplanationOut(BaseModel):
    """Объяснение решения (ТЗ §7)."""

    method: str = Field(description="Способ расчёта вкладов: shap, lightgbm_native или ablation")
    units: str = Field(
        description=(
            "Единицы вклада: logit — вклад в логит базовой модели до калибровки, "
            "probability — в итоговую вероятность"
        )
    )
    base_value: float = Field(description="Базовое значение, от которого отсчитываются вклады")
    summary: str = Field(description="Одна фраза про решение целиком")
    reasons: list[str] = Field(description="Причины: сначала политики, затем факторы модели")
    policy_reasons: list[str] = Field(description="Только сработавшие политики")
    factors: list[RiskFactorOut] = Field(description="3–5 факторов с величиной вклада")


class ThresholdsOut(BaseModel):
    """Пороги, по которым принималось решение."""

    approve_max: int
    challenge_max: int
    critical_min: int


class PredictionResponse(BaseModel):
    """Результат анализа транзакции."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "transaction_id": "txn_a1b2c3d4e5f6",
                "user_id": "user_00042",
                "risk_score": 87,
                "model_score": 87,
                "decision": "BLOCK",
                "risk_level": "HIGH",
                "probability": 0.8712,
                "raised_by_rules": False,
                "processing_ms": 6.1,
            }
        }
    )

    transaction_id: str
    user_id: str
    timestamp: datetime

    risk_score: int = Field(ge=0, le=100, description="Итоговая оценка риска после политик")
    model_score: int = Field(ge=0, le=100, description="Оценка, которую дала только модель")
    probability: float = Field(ge=0.0, le=1.0, description="Вероятность фрода от модели")
    decision: Decision
    risk_level: RiskLevel
    raised_by_rules: bool = Field(description="Подняли ли политики оценку выше модели")

    triggered_rules: list[TriggeredRuleOut] = Field(default_factory=list)
    explanation: ExplanationOut
    thresholds: ThresholdsOut
    features: dict[str, float] = Field(description="Полный вектор признаков транзакции")

    processing_ms: float = Field(description="Время обработки на стороне сервера, мс")
