"""Контракты настройки порогов в рантайме.

Пороги — единственная бизнес-величина, которую разрешено менять
на работающей системе. Остальное (пути к артефактам, параметры датасета,
стоимости) живёт в `.env` и требует перезапуска: менять их на лету
означало бы, что половина системы посчитана по одним правилам,
а половина по другим.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, model_validator


class ThresholdUpdate(BaseModel):
    """Новые пороги Risk Engine."""

    approve_max: int = Field(ge=0, le=100, description="Выше — уже не APPROVE")
    challenge_max: int = Field(ge=0, le=100, description="Выше — уже BLOCK")
    critical_min: int = Field(ge=0, le=100, description="С какого балла риск CRITICAL")
    rules_enabled: bool = Field(
        default=True, description="Применять ли политики поверх решения модели"
    )
    changed_by: str | None = Field(
        default=None,
        max_length=80,
        description="Кто меняет — чтобы спорную правку было с кем обсудить",
    )
    reason: str | None = Field(
        default=None,
        max_length=300,
        description="Зачем: номер обращения, ссылка на разбор, гипотеза",
    )

    @model_validator(mode="after")
    def _thresholds_increase(self) -> ThresholdUpdate:
        """Проверка здесь, а не только в движке.

        Движок бросит `InvalidConfigurationError` и получится 400.
        Но это ошибка данных запроса, и отвечать на неё надо тем же
        кодом 422 и тем же разбором по полям, что и на остальные
        некорректные тела, — иначе клиент разбирает две разные формы
        одной и той же ошибки.
        """
        if self.approve_max >= self.challenge_max:
            raise ValueError(
                f"approve_max ({self.approve_max}) должен быть меньше "
                f"challenge_max ({self.challenge_max})"
            )
        if self.challenge_max >= self.critical_min:
            raise ValueError(
                f"challenge_max ({self.challenge_max}) должен быть меньше "
                f"critical_min ({self.critical_min})"
            )
        return self


class ThresholdChangeOut(BaseModel):
    """Одна правка порогов."""

    at: datetime
    approve_max: int
    challenge_max: int
    critical_min: int
    rules_enabled: bool
    changed_by: str | None = None
    reason: str | None = None


class ThresholdsState(BaseModel):
    """Что действует сейчас и откуда взялось."""

    approve_max: int
    challenge_max: int
    critical_min: int
    rules_enabled: bool
    overridden: bool = Field(
        description=(
            "Пороги меняли в рантайме. false — действуют значения из `.env`. "
            "Перезапуск всегда возвращает к `.env`: неудачную правку отменяет "
            "рестарт, а не поиск того, кто её сделал."
        )
    )
    changed_at: datetime | None = Field(
        default=None, description="Когда меняли в последний раз"
    )
    writable: bool = Field(
        description=(
            "Настроен ли `CONFIG_ADMIN_TOKEN`. false — менять пороги нельзя: "
            "эндпоинт, отключающий блокировки, без пароля открыт кому угодно."
        )
    )
    env_defaults: dict[str, int | bool] = Field(
        description="Значения из `.env` — к ним вернёт перезапуск"
    )
    history: list[ThresholdChangeOut] = Field(
        default_factory=list, description="Последние правки, от свежих к старым"
    )


class ThresholdsApplied(BaseModel):
    """Что изменилось и что из-за этого сброшено."""

    state: ThresholdsState
    shadow_reset: bool = Field(
        description=(
            "Теневое сравнение обнулено. Оно сравнивает две конфигурации, "
            "и если одна изменилась посреди набора, матрица смешивает разное."
        )
    )
    analytics_marked_stale: bool = Field(
        description=(
            "Аналитика на дашборде помечена устаревшей: она посчитана "
            "на прежних порогах."
        )
    )
    drift_kept: bool = Field(
        default=True,
        description=(
            "Наблюдение за дрейфом НЕ сброшено намеренно: оно сравнивает "
            "распределение входных признаков, а пороги на признаки не влияют."
        ),
    )


# ------------------------------------------ адаптивный порог (§6)


class SegmentThresholdOut(BaseModel):
    """Порог одного сегмента и данные, на которых он подобран."""

    segment: str = Field(description="Категория мерчанта")
    approve_max: int = Field(description="Граница «пропустить / проверить» для этого сегмента")
    rows: int
    fraud_rows: int
    fitted: bool = Field(
        description="false — мошеннических операций не хватило, взят общий порог"
    )


class AdaptiveValidationOut(BaseModel):
    """Что даёт режим на данных, которых не видел при подборе.

    Без этих чисел таблица порогов ничего не утверждает. Проверка
    перекрёстная: порог сегмента подбирается без тех строк, на которых
    потом считается результат.
    """

    folds: int
    gain_per_fold: list[float] = Field(
        description="Выигрыш против одного подобранного порога, по частям"
    )
    mean_gain: float
    worst_gain: float = Field(description="Худшая часть. Отрицательная — режим там проиграл")
    positive_folds: int

    configured_approve_max: int = Field(description="Действующая настройка, с которой сравниваем")
    configured_cost: float
    adaptive_cost: float
    configured_friction: int
    adaptive_friction: int
    configured_fraud_stopped: int
    adaptive_fraud_stopped: int


class AdaptiveThresholdsState(BaseModel):
    """Подобранные пороги, их проверка и признак применения."""

    available: bool = Field(description="Подобраны ли пороги вообще")
    enabled: bool = Field(description="Применяются ли они к решениям прямо сейчас")
    error: str | None = Field(
        default=None, description="Почему артефакт не прочитался"
    )
    generated_at: str | None = None
    rows: int | None = None
    min_fraud_per_segment: int | None = None
    fallback_approve_max: int | None = Field(
        default=None, description="Порог для сегментов без своего"
    )
    segments: list[SegmentThresholdOut] = Field(default_factory=list)
    validation: AdaptiveValidationOut | None = None
