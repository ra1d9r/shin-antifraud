"""Контракт входящей транзакции (ТЗ §3).

Обязательные поля соответствуют ТЗ дословно. Дополнительно приняты
опциональные поля контекста клиента — решение [D-4](../../../docs/TZ.md):
без истории невозможно посчитать «отклонение от обычного поведения».

Приоритет источников контекста при обработке запроса:

1. поле явно передано в запросе — используется оно;
2. поля нет, но клиент уже известен системе — берётся из профиля;
3. клиент новый — работают нейтральные значения по умолчанию.

Первый пункт важен для ручного тестирования: если симулятор передаёт
контекст явно, повторный запрос с теми же данными даёт тот же ответ
независимо от накопленной истории.
"""

from __future__ import annotations

import ipaddress
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TransactionRequest(BaseModel):
    """Транзакция, поступившая на анализ."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "user_id": "user_00042",
                "amount": 2500.0,
                "merchant": "Binance",
                "country": "NG",
                "device_id": "dev_unknown_77",
                "ip_address": "197.210.44.12",
                "latitude": 6.5244,
                "longitude": 3.3792,
                "transaction_frequency": 14,
                "previous_transaction_amount": 95.0,
                "previous_transaction_country": "KZ",
                "account_age_days": 800,
                "user_avg_amount": 100.0,
                "user_home_country": "KZ",
                "known_device_ids": ["dev_known_1", "dev_known_2"],
            }
        }
    )

    # ------------------------------------------------------------ ТЗ §3
    transaction_id: str = Field(
        default_factory=lambda: f"txn_{uuid.uuid4().hex[:12]}",
        description="Идентификатор транзакции. Если не передан — генерируется.",
    )
    user_id: str = Field(min_length=1, max_length=128, description="Идентификатор клиента")
    amount: float = Field(gt=0, le=1e9, description="Сумма транзакции")
    timestamp: datetime | None = Field(
        default=None,
        description="Время транзакции. Если не передано — текущее время UTC.",
    )
    merchant: str = Field(min_length=1, max_length=128, description="Мерчант")
    country: str = Field(min_length=2, max_length=2, description="Код страны ISO-3166 alpha-2")
    device_id: str = Field(min_length=1, max_length=128, description="Идентификатор устройства")
    ip_address: str = Field(description="IP-адрес")
    latitude: float = Field(ge=-90.0, le=90.0, description="Широта")
    longitude: float = Field(ge=-180.0, le=180.0, description="Долгота")
    transaction_frequency: int = Field(
        ge=0, le=100_000, description="Число операций клиента за последние 24 часа"
    )
    previous_transaction_amount: float = Field(
        ge=0, le=1e9, description="Сумма предыдущей транзакции"
    )
    previous_transaction_country: str = Field(
        min_length=2, max_length=2, description="Страна предыдущей транзакции"
    )
    account_age_days: int = Field(ge=0, le=100_000, description="Возраст счёта в днях")

    # ------------------------------------------- контекст клиента (D-4)
    user_avg_amount: float | None = Field(default=None, gt=0, description="Обычная сумма клиента")
    user_amount_std: float | None = Field(
        default=None, ge=0, description="Разброс сумм клиента"
    )
    user_home_country: str | None = Field(
        default=None, min_length=2, max_length=2, description="Домашняя страна клиента"
    )
    user_typical_frequency: float | None = Field(
        default=None, gt=0, description="Обычное число операций в сутки"
    )
    known_device_ids: list[str] | None = Field(
        default=None, description="Устройства, ранее замеченные у клиента"
    )
    previous_ip_address: str | None = Field(default=None, description="IP предыдущей транзакции")
    previous_timestamp: datetime | None = Field(
        default=None, description="Время предыдущей транзакции"
    )
    previous_latitude: float | None = Field(default=None, ge=-90.0, le=90.0)
    previous_longitude: float | None = Field(default=None, ge=-180.0, le=180.0)
    txn_count_last_hour: int | None = Field(
        default=None, ge=0, le=100_000, description="Число операций за последний час"
    )
    merchant_category: str | None = Field(
        default=None, max_length=64, description="Категория мерчанта; иначе берётся из справочника"
    )

    # ------------------------------------------------------- поведение
    persist: bool = Field(
        default=True,
        description=(
            "Сохранять ли транзакцию в историю и обновлять профиль клиента. "
            "false — режим «что если»: ответ считается, но состояние системы "
            "не меняется, поэтому повторный запрос даёт тот же результат."
        ),
    )

    # ------------------------------------------------------ валидаторы
    @field_validator("country", "previous_transaction_country", "user_home_country")
    @classmethod
    def _normalize_country(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().upper()
        if not normalized.isalpha():
            raise ValueError("Код страны должен состоять из двух букв, например KZ")
        return normalized

    @field_validator("ip_address", "previous_ip_address")
    @classmethod
    def _validate_ip(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            ipaddress.ip_address(value.strip())
        except ValueError as exc:
            raise ValueError(f"Некорректный IP-адрес: {value!r}") from exc
        return value.strip()

    @field_validator("known_device_ids")
    @classmethod
    def _clean_devices(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return [item.strip() for item in value if item and item.strip()]
