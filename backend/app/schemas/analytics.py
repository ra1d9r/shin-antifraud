"""Контракт аналитики по всему датасету (брифинг §5.A, §11).

Схемы описаны явно, а не отдаются сырым словарём, ради Swagger: жюри
открывает документацию и видит, что именно считает система, без чтения кода.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class DecisionRowOut(BaseModel):
    """Сколько легальных и мошеннических операций получили это решение."""

    decision: str = Field(description="APPROVE / CHALLENGE / BLOCK")
    legit: int
    fraud: int


class RuleStatOut(BaseModel):
    """Статистика политики и её предельный вклад сверх модели."""

    key: str
    title: str
    min_score: int
    legit_hits: int = Field(description="Сработала на легальной операции")
    fraud_hits: int = Field(description="Сработала на мошеннической операции")
    precision: float = Field(description="Доля фрода среди всех срабатываний")
    gained_fraud: int = Field(
        description="Фрод, пойманный сверх того, что уже остановила модель"
    )
    added_friction: int = Field(
        description="Добросовестные клиенты, задетые сверх решения модели"
    )
    checks_per_fraud: float | None = Field(
        default=None,
        description=(
            "Цена одного дополнительно пойманного фрода в лишних проверках. "
            "null — политика не поймала ничего сверх модели, то есть даёт "
            "только трение."
        ),
    )


class CurvePointOut(BaseModel):
    """Точка кривой компромисса при одном пороге чувствительности."""

    threshold: int = Field(description="Всё выше этого Risk Score уходит на проверку")
    fraud_missed: int
    fraud_stopped: int
    friction: int = Field(description="Задетые добросовестные клиенты")
    fraud_loss: float
    friction_cost: float
    total_cost: float


class AnalyticsOverview(BaseModel):
    """Полная картина работы системы на датасете."""

    generated_at: str = Field(description="Когда выгружена аналитика")
    rows: int
    fraud_rows: int
    legit_rows: int
    fraud_rate: float
    total_amount: float

    thresholds: dict[str, int]
    rules_enabled: bool

    decisions: list[DecisionRowOut]
    fraud_blocked: int
    fraud_stopped: int = Field(description="Фрод с решением, отличным от APPROVE")
    fraud_missed: int
    fraud_stopped_share: float
    friction: int = Field(
        description="Легальные операции с решением, отличным от APPROVE"
    )
    friction_share: float = Field(
        description="False Positive Rate: доля задетых добросовестных клиентов"
    )
    raised_by_rules: int

    rules: list[RuleStatOut]
    cost_with_rules: float
    cost_without_rules: float
    rules_cost_delta: float = Field(
        description="Во что обходятся политики сверх чистой модели. Меньше нуля — окупаются."
    )

    curve: list[CurvePointOut]
    optimal_threshold: int = Field(
        description="Порог с наименьшей суммарной стоимостью по модели из конфигурации"
    )
