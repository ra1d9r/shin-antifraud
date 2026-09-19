"""Реестр признаков (ТЗ §4).

Каждый признак описан один раз и в одном месте: техническое имя, русское
описание для документации и англоязычные формулировки для XAI (ТЗ §7 приводит
примеры причин на английском).

Порядок `FEATURE_SPECS` — это порядок колонок вектора признаков. Он сохраняется
вместе с моделью, поэтому менять его можно только вместе с переобучением.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FeatureSpec:
    """Описание одного признака."""

    name: str
    description: str
    # Формулировка, когда признак ПОВЫШАЕТ риск. Может содержать {value}.
    reason_high: str
    # Формулировка, когда признак ПОНИЖАЕТ риск. None — о таком не рассказываем.
    reason_low: str | None = None
    # Бинарный признак: значение в текст не подставляется.
    is_flag: bool = False
    value_format: str = "{:.2f}"

    def format_value(self, value: float) -> str:
        if self.is_flag:
            return "yes" if value >= 0.5 else "no"
        return self.value_format.format(value)


FEATURE_SPECS: tuple[FeatureSpec, ...] = (
    # ------------------------------------------------ сумма (ТЗ §4.1)
    FeatureSpec(
        name="amount_log",
        description="Логарифм суммы транзакции",
        # Значение в текст не подставляется: пользователю нечего делать
        # с логарифмом. Само число всё равно возвращается в поле value.
        reason_high="Large transaction amount in absolute terms",
        value_format="{:.2f}",
    ),
    FeatureSpec(
        name="amount_deviation_ratio",
        description="Во сколько раз сумма отличается от обычной суммы клиента",
        reason_high="Transaction amount is {value}x the user's normal amount",
        reason_low="Amount is in line with the user's normal spending",
        value_format="{:.1f}",
    ),
    FeatureSpec(
        name="amount_zscore",
        description="Отклонение суммы от обычной в стандартных отклонениях клиента",
        reason_high="Amount deviates {value} standard deviations from the user's usual spending",
        value_format="{:.1f}",
    ),
    FeatureSpec(
        name="amount_vs_previous_ratio",
        description="Отношение суммы к сумме предыдущей транзакции",
        reason_high="Amount is {value}x the user's previous transaction",
        value_format="{:.1f}",
    ),
    FeatureSpec(
        name="is_round_amount",
        description="Круглая сумма — характерна для попыток вывода средств",
        reason_high="Round-number amount, typical of cash-out attempts",
        is_flag=True,
    ),
    FeatureSpec(
        name="is_micro_amount",
        description="Необычно мелкая сумма — характерна для прозвона карты",
        reason_high="Unusually small amount, typical of card-testing probes",
        is_flag=True,
    ),
    # ------------------------------------------------ страна (ТЗ §4.2)
    FeatureSpec(
        name="is_unusual_country",
        description="Транзакция вне домашней страны клиента",
        reason_high="Unusual country: transaction outside the user's home country",
        reason_low="Transaction from the user's home country",
        is_flag=True,
    ),
    FeatureSpec(
        name="country_changed_from_previous",
        description="Страна изменилась относительно предыдущей транзакции",
        reason_high="Country changed since the previous transaction",
        is_flag=True,
    ),
    FeatureSpec(
        name="is_high_risk_country",
        description="Страна входит в список повышенного риска",
        reason_high="Transaction from a high-risk country",
        is_flag=True,
    ),
    # ------------------------------------------------ устройство (ТЗ §4.3)
    FeatureSpec(
        name="is_new_device",
        description="Устройство ранее не встречалось у этого клиента",
        reason_high="New device detected",
        reason_low="Device is already known for this user",
        is_flag=True,
    ),
    FeatureSpec(
        name="known_device_count",
        description="Сколько устройств известно для клиента",
        reason_high="User has {value} known devices",
        value_format="{:.0f}",
    ),
    # ------------------------------------------------ IP (ТЗ §4.4)
    FeatureSpec(
        name="ip_changed",
        description="IP-адрес отличается от предыдущего",
        reason_high="IP address changed since the previous transaction",
        is_flag=True,
    ),
    FeatureSpec(
        name="ip_subnet_changed",
        description="Сменилась подсеть /24 — другой провайдер или сеть",
        reason_high="Network changed: different IP subnet than the previous transaction",
        reason_low="Same network as the previous transaction",
        is_flag=True,
    ),
    # ------------------------------------------------ частота (ТЗ §4.5, §4.8)
    FeatureSpec(
        name="transaction_frequency",
        description="Количество транзакций клиента за последние 24 часа",
        reason_high="{value} transactions in the last 24 hours",
        value_format="{:.0f}",
    ),
    FeatureSpec(
        name="frequency_ratio",
        description="Во сколько раз текущая частота выше обычной для клиента",
        reason_high="Transaction frequency is {value}x the user's normal rate",
        reason_low="Transaction frequency is normal for this user",
        value_format="{:.1f}",
    ),
    FeatureSpec(
        name="txn_count_last_hour",
        description="Количество транзакций за последний час",
        reason_high="{value} transactions in the last hour",
        value_format="{:.0f}",
    ),
    FeatureSpec(
        name="is_high_frequency",
        description="Частота транзакций существенно выше обычной",
        reason_high="High transaction frequency for this user",
        is_flag=True,
    ),
    # ------------------------------------------------ геолокация (ТЗ §4.6)
    FeatureSpec(
        name="geo_distance_km",
        description="Расстояние до места предыдущей транзакции, км",
        reason_high="Transaction {value} km away from the previous one",
        value_format="{:.0f}",
    ),
    FeatureSpec(
        name="hours_since_previous",
        description="Часов прошло с предыдущей транзакции",
        reason_high="Only {value} hours since the previous transaction",
        value_format="{:.2f}",
    ),
    FeatureSpec(
        name="travel_speed_kmh",
        description="Требуемая скорость перемещения между транзакциями, км/ч",
        reason_high="Implied travel speed of {value} km/h between transactions",
        value_format="{:.0f}",
    ),
    FeatureSpec(
        name="is_impossible_travel",
        description="Перемещение физически невозможно за прошедшее время",
        reason_high="Impossible travel: this location cannot be reached in the elapsed time",
        is_flag=True,
    ),
    # ------------------------------------------------ время (ТЗ §4.7)
    FeatureSpec(
        name="hour_of_day",
        description="Час суток",
        reason_high="Transaction at {value}:00",
        value_format="{:.0f}",
    ),
    FeatureSpec(
        name="is_night",
        description="Ночное время (00:00–05:59)",
        reason_high="Night-time transaction",
        reason_low="Transaction during normal daytime hours",
        is_flag=True,
    ),
    FeatureSpec(
        name="is_weekend",
        description="Выходной день",
        reason_high="Weekend transaction",
        is_flag=True,
    ),
    # ------------------------------------------------ счёт и мерчант
    FeatureSpec(
        name="account_age_days",
        description="Возраст счёта в днях",
        reason_high="Account age is {value} days",
        reason_low="Long-standing account",
        value_format="{:.0f}",
    ),
    FeatureSpec(
        name="is_new_account",
        description="Счёт открыт недавно (моложе 60 дней)",
        reason_high="Recently opened account",
        is_flag=True,
    ),
    FeatureSpec(
        name="is_high_risk_merchant",
        description="Категория мерчанта повышенного риска (crypto, gambling, переводы, ATM)",
        reason_high="High-risk merchant category (crypto, gambling, transfers or ATM)",
        is_flag=True,
    ),
)

FEATURE_NAMES: tuple[str, ...] = tuple(spec.name for spec in FEATURE_SPECS)

_SPEC_BY_NAME: dict[str, FeatureSpec] = {spec.name: spec for spec in FEATURE_SPECS}


def get_spec(name: str) -> FeatureSpec:
    """Описание признака по имени."""
    try:
        return _SPEC_BY_NAME[name]
    except KeyError as exc:
        raise KeyError(f"Неизвестный признак: {name}") from exc


def has_spec(name: str) -> bool:
    return name in _SPEC_BY_NAME
