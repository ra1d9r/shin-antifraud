"""Контракты теневого режима.

Домен живёт в `app.monitoring.shadow`; здесь только то, что уходит в HTTP.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.enums import Decision


class ConfigurationOut(BaseModel):
    """Одна конфигурация Risk Engine."""

    approve_max: int
    challenge_max: int
    critical_min: int
    rules_enabled: bool


class MatrixCellOut(BaseModel):
    """Сколько операций получили такую пару решений и на какую сумму."""

    primary: Decision = Field(description="Решение основной конфигурации")
    shadow: Decision = Field(description="Решение теневой")
    count: int
    amount: float


class DisagreementOut(BaseModel):
    """Операция, по которой конфигурации разошлись."""

    transaction_id: str
    user_id: str
    amount: float
    primary_decision: Decision
    primary_score: int
    shadow_decision: Decision
    shadow_score: int
    at: datetime


class ShadowComparison(BaseModel):
    """Что дало бы переключение конфигурации на этом потоке."""

    enabled: bool
    differs: bool = Field(
        description=(
            "Теневая конфигурация отличается от основной. false — сравнивать "
            "нечего, и стопроцентное согласие ничего не означает."
        )
    )
    difference: str = Field(description="Чем отличается — словами")
    primary: ConfigurationOut
    shadow: ConfigurationOut
    observed: int = Field(description="Операций прошло через обе конфигурации")
    agreed: int
    disagreed: int
    agreement_share: float | None = Field(
        default=None, description="null — операций ещё не было, делить не на что"
    )
    freed_count: int = Field(
        description="Основная пометила, теневая пропустила бы: снятое трение"
    )
    freed_amount: float = Field(description="На какую сумму снялось бы трение")
    tightened_count: int = Field(
        description="Основная пропустила, теневая пометила бы: новое трение"
    )
    tightened_amount: float
    matrix: list[MatrixCellOut] = Field(
        default_factory=list, description="Решение основной против решения теневой"
    )
    recent: list[DisagreementOut] = Field(
        default_factory=list, description="Последние расхождения — для разбора"
    )
