"""Feature engineering (ТЗ §4).

Модуль превращает транзакцию плюс контекст клиента в вектор признаков.
Здесь нет ни FastAPI, ни ML-библиотек — только вычисление признаков.

Ключевое архитектурное свойство: **один и тот же код считает признаки
и при обучении, и при инференсе**. Батч-функция `build_feature_frame`
вызывает ту же `build_features`, что и API, построчно. Это медленнее
векторизации, но полностью исключает training/serving skew — ситуацию,
когда модель обучена на одних формулах, а в проде получает другие.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from app.core.exceptions import FeatureBuildError
from app.features.definitions import FEATURE_NAMES
from app.features.geo import haversine_km, is_high_risk_country, is_impossible_travel, travel_speed_kmh
from app.features.merchants import is_high_risk_category, merchant_category

# Пороговые значения признаков вынесены в константы, чтобы они не были
# «магическими числами», разбросанными по коду.
# Порог «нового счёта». Импортируется генератором датасета, чтобы определение
# признака и определение сценария new_account_abuse не разошлись.
NEW_ACCOUNT_THRESHOLD_DAYS = 60
HIGH_FREQUENCY_RATIO = 3.0
MICRO_AMOUNT_ABSOLUTE = 10.0
MICRO_AMOUNT_RELATIVE = 0.25
ROUND_AMOUNT_STEP = 50.0
NIGHT_HOURS = range(0, 6)

# Ограничители, чтобы отношения не улетали в бесконечность на вырожденных входах.
MAX_RATIO = 1_000.0
MAX_ZSCORE = 50.0
MAX_SPEED_KMH = 100_000.0

# Нейтральные значения, когда контекста нет (первая транзакция клиента).
DEFAULT_HOURS_SINCE_PREVIOUS = 24.0


def _is_missing(value: object) -> bool:
    """NaN / NaT / None.

    `pandas.NaT` — подкласс `datetime`, поэтому проверка `isinstance` его
    пропускает. Ловим по свойству «не равно самому себе», общему для NaN и NaT.
    """
    if value is None:
        return True
    return value != value  # noqa: PLR0124 — намеренная проверка на NaN/NaT


def normalize_timestamp(value: datetime) -> datetime:
    """Привести время к наивному UTC.

    Клиенты присылают время и с таймзоной, и без. Смешивать их нельзя:
    арифметика между aware и naive datetime падает с TypeError.

    Приводим именно к UTC, а не к локальной зоне: иначе час транзакции —
    а значит и признак `is_night` — зависел бы от того, в какой зоне
    запущен сервер.
    """
    if not isinstance(value, datetime) or _is_missing(value):
        raise FeatureBuildError(
            f"Ожидалось значение времени, получено {type(value).__name__}: {value!r}. "
            "При чтении CSV используйте parse_dates=['timestamp', 'previous_timestamp']."
        )
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


@dataclass(slots=True)
class TransactionInput:
    """Транзакция плюс контекст клиента — вход feature engineering.

    Обязательные поля соответствуют ТЗ §3. Контекстные поля опциональны:
    при инференсе их подставляет хранилище профилей, а при их отсутствии
    работают разумные значения по умолчанию (см. `_resolve_context`).
    """

    # --- ТЗ §3
    transaction_id: str
    user_id: str
    amount: float
    timestamp: datetime
    merchant: str
    country: str
    device_id: str
    ip_address: str
    latitude: float
    longitude: float
    transaction_frequency: int
    previous_transaction_amount: float
    previous_transaction_country: str
    account_age_days: int

    # --- контекст клиента (решение D-4 в docs/TZ.md)
    user_avg_amount: float | None = None
    user_amount_std: float | None = None
    user_home_country: str | None = None
    user_typical_frequency: float | None = None
    known_device_ids: tuple[str, ...] = field(default_factory=tuple)
    previous_ip_address: str | None = None
    previous_timestamp: datetime | None = None
    previous_latitude: float | None = None
    previous_longitude: float | None = None
    txn_count_last_hour: int | None = None
    merchant_category: str | None = None


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _safe_ratio(numerator: float, denominator: float) -> float:
    """Отношение, устойчивое к нулевому и отрицательному знаменателю."""
    return _clip(numerator / max(abs(denominator), 0.01), 0.0, MAX_RATIO)


def _ip_subnet(ip_address: str | None) -> str | None:
    """Первые три октета IPv4 — подсеть /24."""
    if not ip_address:
        return None
    parts = ip_address.split(".")
    return ".".join(parts[:3]) if len(parts) >= 3 else ip_address


def _is_round_amount(amount: float) -> bool:
    """Круглая сумма, кратная 50, — характерна для попыток вывода средств."""
    if amount < ROUND_AMOUNT_STEP:
        return False
    remainder = amount % ROUND_AMOUNT_STEP
    # Остаток может быть близок как к нулю, так и к самому шагу (150.0 при
    # накоплении погрешности представляется как 149.999...).
    return remainder < 0.005 or remainder > ROUND_AMOUNT_STEP - 0.005


def build_features(transaction: TransactionInput) -> dict[str, float]:
    """Построить признаки для одной транзакции.

    Возвращает словарь `имя признака -> значение`. Ключи и их порядок
    совпадают с `FEATURE_NAMES`.
    """
    timestamp = normalize_timestamp(transaction.timestamp)

    # ---------------------------------------------------- контекст клиента
    avg_amount = transaction.user_avg_amount
    if avg_amount is None or avg_amount <= 0:
        # Без профиля лучшее доступное приближение — предыдущая сумма.
        avg_amount = max(transaction.previous_transaction_amount, 0.01)

    amount_std = transaction.user_amount_std
    if amount_std is None or amount_std <= 0:
        amount_std = avg_amount * 0.5

    home_country = transaction.user_home_country or transaction.previous_transaction_country
    typical_frequency = transaction.user_typical_frequency
    if typical_frequency is None or typical_frequency <= 0:
        typical_frequency = 1.0

    category = transaction.merchant_category or merchant_category(transaction.merchant)

    # ---------------------------------------------------- сумма (ТЗ §4.1)
    amount = max(transaction.amount, 0.0)
    amount_deviation_ratio = _safe_ratio(amount, avg_amount)
    amount_zscore = _clip((amount - avg_amount) / max(amount_std, 0.01), -MAX_ZSCORE, MAX_ZSCORE)
    amount_vs_previous_ratio = _safe_ratio(amount, transaction.previous_transaction_amount)
    is_micro_amount = amount < MICRO_AMOUNT_ABSOLUTE and amount < avg_amount * MICRO_AMOUNT_RELATIVE

    # ---------------------------------------------------- устройство (ТЗ §4.3)
    known_devices = tuple(transaction.known_device_ids)
    # Пустой список устройств означает «истории нет», а не «устройство новое»:
    # объявлять первую в жизни транзакцию подозрительной было бы неверно.
    is_new_device = bool(known_devices) and transaction.device_id not in known_devices

    # ---------------------------------------------------- IP (ТЗ §4.4)
    previous_ip = transaction.previous_ip_address
    ip_changed = bool(previous_ip) and transaction.ip_address != previous_ip
    ip_subnet_changed = bool(previous_ip) and _ip_subnet(transaction.ip_address) != _ip_subnet(previous_ip)

    # ---------------------------------------------------- частота (ТЗ §4.5, §4.8)
    frequency = float(max(transaction.transaction_frequency, 0))
    frequency_ratio = _clip(frequency / max(typical_frequency, 0.1), 0.0, 100.0)
    count_last_hour = transaction.txn_count_last_hour
    if count_last_hour is None:
        count_last_hour = 1

    # ---------------------------------------------------- геолокация (ТЗ §4.6)
    previous_timestamp = (
        normalize_timestamp(transaction.previous_timestamp)
        if transaction.previous_timestamp is not None
        else None
    )
    if previous_timestamp is not None:
        elapsed = (timestamp - previous_timestamp).total_seconds() / 3600.0
        hours_since_previous = max(elapsed, 0.0)
    else:
        hours_since_previous = DEFAULT_HOURS_SINCE_PREVIOUS

    if transaction.previous_latitude is not None and transaction.previous_longitude is not None:
        geo_distance = haversine_km(
            transaction.previous_latitude,
            transaction.previous_longitude,
            transaction.latitude,
            transaction.longitude,
        )
    else:
        geo_distance = 0.0

    speed = _clip(travel_speed_kmh(geo_distance, hours_since_previous), 0.0, MAX_SPEED_KMH)
    impossible_travel = is_impossible_travel(geo_distance, hours_since_previous)

    # ---------------------------------------------------- итоговый словарь
    features: dict[str, float] = {
        "amount_log": math.log1p(amount),
        "amount_deviation_ratio": amount_deviation_ratio,
        "amount_zscore": amount_zscore,
        "amount_vs_previous_ratio": amount_vs_previous_ratio,
        "is_round_amount": float(_is_round_amount(amount)),
        "is_micro_amount": float(is_micro_amount),

        "is_unusual_country": float(bool(home_country) and transaction.country != home_country),
        "country_changed_from_previous": float(
            transaction.country != transaction.previous_transaction_country
        ),
        "is_high_risk_country": float(is_high_risk_country(transaction.country)),

        "is_new_device": float(is_new_device),
        "known_device_count": float(len(known_devices)),

        "ip_changed": float(ip_changed),
        "ip_subnet_changed": float(ip_subnet_changed),

        "transaction_frequency": frequency,
        "frequency_ratio": frequency_ratio,
        "txn_count_last_hour": float(max(count_last_hour, 0)),
        "is_high_frequency": float(frequency_ratio >= HIGH_FREQUENCY_RATIO),

        "geo_distance_km": geo_distance,
        "hours_since_previous": hours_since_previous,
        "travel_speed_kmh": speed,
        "is_impossible_travel": float(impossible_travel),

        "hour_of_day": float(timestamp.hour),
        "is_night": float(timestamp.hour in NIGHT_HOURS),
        "is_weekend": float(timestamp.weekday() >= 5),

        "account_age_days": float(max(transaction.account_age_days, 0)),
        "is_new_account": float(transaction.account_age_days <= NEW_ACCOUNT_THRESHOLD_DAYS),
        "is_high_risk_merchant": float(is_high_risk_category(category)),
    }

    # Ни один признак не имеет права быть NaN или бесконечностью: такое
    # значение тихо разрушает и обучение, и предсказание.
    for name, value in features.items():
        if not math.isfinite(value):
            raise FeatureBuildError(
                f"Признак {name} получил недопустимое значение {value!r} "
                f"для транзакции {transaction.transaction_id}"
            )

    # Страховка от рассинхронизации реестра и вычислений.
    if tuple(features.keys()) != FEATURE_NAMES:
        missing = set(FEATURE_NAMES) - set(features)
        extra = set(features) - set(FEATURE_NAMES)
        raise RuntimeError(
            f"Набор признаков разошёлся с реестром. Нет: {missing or '—'}; лишние: {extra or '—'}"
        )

    return features


def build_feature_vector(transaction: TransactionInput) -> list[float]:
    """Вектор признаков в порядке `FEATURE_NAMES`."""
    features = build_features(transaction)
    return [features[name] for name in FEATURE_NAMES]


# --------------------------------------------------------------- batch mode


def _parse_device_list(raw: object) -> tuple[str, ...]:
    """Список устройств хранится в CSV строкой 'dev_a|dev_b'."""
    if raw is None or not isinstance(raw, str) or not raw:
        return ()
    return tuple(part for part in raw.split("|") if part)


def transaction_from_row(row: dict) -> TransactionInput:
    """Собрать `TransactionInput` из строки датасета."""

    def optional_float(key: str) -> float | None:
        value = row.get(key)
        if _is_missing(value):
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return None if math.isnan(number) else number

    def optional_str(key: str) -> str | None:
        value = row.get(key)
        if _is_missing(value) or not isinstance(value, str) or not value:
            return None
        return value

    def optional_datetime(key: str) -> datetime | None:
        value = row.get(key)
        if _is_missing(value) or not isinstance(value, datetime):
            return None
        return value

    return TransactionInput(
        transaction_id=str(row["transaction_id"]),
        user_id=str(row["user_id"]),
        amount=float(row["amount"]),
        timestamp=row["timestamp"],
        merchant=str(row["merchant"]),
        country=str(row["country"]),
        device_id=str(row["device_id"]),
        ip_address=str(row["ip_address"]),
        latitude=float(row["latitude"]),
        longitude=float(row["longitude"]),
        transaction_frequency=int(row["transaction_frequency"]),
        previous_transaction_amount=float(row["previous_transaction_amount"]),
        previous_transaction_country=str(row["previous_transaction_country"]),
        account_age_days=int(row["account_age_days"]),
        user_avg_amount=optional_float("user_avg_amount"),
        user_amount_std=optional_float("user_amount_std"),
        user_home_country=optional_str("user_home_country"),
        user_typical_frequency=optional_float("user_typical_frequency"),
        known_device_ids=_parse_device_list(row.get("known_device_ids")),
        previous_ip_address=optional_str("previous_ip_address"),
        previous_timestamp=optional_datetime("previous_timestamp"),
        previous_latitude=optional_float("previous_latitude"),
        previous_longitude=optional_float("previous_longitude"),
        txn_count_last_hour=(
            int(row["txn_count_last_hour"]) if row.get("txn_count_last_hour") is not None else None
        ),
        merchant_category=optional_str("merchant_category"),
    )


def build_feature_frame(frame):  # type: ignore[no-untyped-def]
    """Построить матрицу признаков для датасета.

    Импорт pandas локальный: модуль признаков должен оставаться пригодным
    к использованию в API, где pandas не нужен для одиночного предсказания.
    """
    import pandas as pd

    records = frame.to_dict(orient="records")
    rows = [build_features(transaction_from_row(record)) for record in records]
    return pd.DataFrame(rows, columns=list(FEATURE_NAMES), index=frame.index)
