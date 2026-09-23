"""Контракты наблюдения за системой в работе.

Домен живёт в `app.monitoring.drift`; здесь только то, что уходит в HTTP.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.monitoring.drift import DriftStatus


class FeatureDriftOut(BaseModel):
    """Насколько один признак в проде разошёлся с обучающим."""

    name: str
    description: str = Field(description="Что означает признак — человеку, а не модели")
    status: DriftStatus
    psi: float | None = Field(
        default=None,
        description=(
            "Population Stability Index. null — сравнивать нечего: "
            "признак в обучающей выборке постоянен либо наблюдений пока мало."
        ),
    )
    labels: list[str] = Field(
        default_factory=list, description="Подписи корзин: границы или «нет»/«да»"
    )
    expected: list[float] = Field(
        default_factory=list, description="Доли корзин в обучающей выборке"
    )
    observed: list[float] = Field(
        default_factory=list, description="Доли корзин в живом потоке"
    )


class DriftReportOut(BaseModel):
    """Сводка по сдвигу распределения признаков."""

    status: DriftStatus = Field(
        description=(
            "Худший признак, а не средний: один уехавший среди двадцати семи "
            "усреднением растворяется, а вход модели портит."
        )
    )
    observed_rows: int = Field(description="Сколько операций прошло через систему с запуска")
    baseline_rows: int = Field(description="На скольких строках снят эталон")
    baseline_generated_at: str
    model_trained_at: str | None = Field(
        default=None,
        description=(
            "Метка модели на момент снятия эталона. Справочно: эталон описывает "
            "датасет, а не модель, и переобучение на тех же данных его не портит."
        ),
    )
    min_observations: int = Field(description="Сколько наблюдений нужно, чтобы называть числа")
    enough_data: bool
    drifted: int = Field(description="Сколько признаков вышло за границу стабильности")
    invalid_values: int = Field(
        description="Сколько раз признак пришёл нечисловым — так быть не должно"
    )
    features: list[FeatureDriftOut] = Field(
        default_factory=list, description="По убыванию PSI: разошедшееся сверху"
    )
