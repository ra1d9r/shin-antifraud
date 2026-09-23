"""Генератор синтетического датасета транзакций (ТЗ §5.1–5.2).

Принцип генерации — главное отличие этого модуля от «случайных чисел с меткой»:

1. Сначала создаются **профили клиентов**: домашняя страна, обычная сумма,
   свои устройства, своя IP-подсеть, привычные мерчанты, обычная частота.
2. Затем для каждого клиента строится **хронологическая лента** транзакций,
   где каждая следующая транзакция знает о предыдущей.
3. Фрод не «помечается случайно», а **порождается сценариями атак**
   (см. `FraudScenario`), каждый со своей механикой.
4. В легальные транзакции намеренно вносятся аномалии-обманки: реальные поездки,
   покупка нового телефона, смена провайдера, крупная законная покупка.

Пункт 4 обязателен. Без него классы разделяются тривиально, модель получает
ROC-AUC ~1.0 и на демонстрации ведёт себя неправдоподобно.

Валюта сумм — условные USD.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum

import pandas as pd

from app.features.builder import NEW_ACCOUNT_THRESHOLD_DAYS
from app.features.geo import (
    COMMON_TRAVEL_COUNTRIES,
    COUNTRY_COORDINATES,
    DATACENTER_PREFIXES,
    HIGH_RISK_COUNTRY_LIST,
    country_coordinates,
    haversine_km,
)
from app.features.merchants import (
    ALL_MERCHANTS,
    BIG_TICKET_MERCHANTS,
    CARD_TESTING_MERCHANTS,
    CASHOUT_MERCHANTS,
    EVERYDAY_MERCHANTS,
    MERCHANT_CATEGORY,
    SMALL_TICKET_MERCHANTS,
)

# Опорная дата конца выборки. Фиксирована, чтобы датасет был воспроизводим
# при одном и том же seed независимо от дня запуска.
DEFAULT_END_DATE = datetime(2026, 9, 1, 0, 0, 0)
DATASET_SPAN_DAYS = 180

# Запас времени в конце окна. Эпизод фрода добавляет собственные интервалы
# поверх нарисованного момента старта (прозвон карты — до 14 списаний,
# злоупотребление новым счётом — до 3 операций с паузами по 2 часа).
# Без запаса лента может выйти за правую границу окна наблюдения.
EPISODE_TIME_MARGIN_DAYS = 0.35

# Домашние страны клиентов: регион Центральной Азии как основной рынок.
HOME_COUNTRY_WEIGHTS: dict[str, float] = {
    "KZ": 0.62, "UZ": 0.10, "KG": 0.07, "RU": 0.08,
    "AZ": 0.04, "GE": 0.03, "TR": 0.03, "DE": 0.03,
}


class FraudScenario(StrEnum):
    """Сценарии атак, которыми порождается фрод."""

    NONE = "none"
    ACCOUNT_TAKEOVER = "account_takeover"
    CARD_TESTING = "card_testing"
    IMPOSSIBLE_TRAVEL = "impossible_travel"
    NEW_DEVICE_CASHOUT = "new_device_cashout"
    AMOUNT_ANOMALY = "amount_anomaly"
    NEW_ACCOUNT_ABUSE = "new_account_abuse"
    QUIET_FRAUD = "quiet_fraud"


# Сколько транзакций порождает один эпизод каждого сценария.
SCENARIO_EPISODE_LENGTH: dict[FraudScenario, tuple[int, int]] = {
    FraudScenario.ACCOUNT_TAKEOVER: (2, 6),
    FraudScenario.CARD_TESTING: (5, 14),
    FraudScenario.IMPOSSIBLE_TRAVEL: (1, 3),
    FraudScenario.NEW_DEVICE_CASHOUT: (1, 4),
    FraudScenario.AMOUNT_ANOMALY: (1, 2),
    FraudScenario.NEW_ACCOUNT_ABUSE: (1, 3),
    FraudScenario.QUIET_FRAUD: (1, 2),
}

# Относительная частота сценариев в датасете.
SCENARIO_WEIGHTS: dict[FraudScenario, float] = {
    FraudScenario.ACCOUNT_TAKEOVER: 0.20,
    FraudScenario.CARD_TESTING: 0.12,
    FraudScenario.IMPOSSIBLE_TRAVEL: 0.12,
    FraudScenario.NEW_DEVICE_CASHOUT: 0.14,
    FraudScenario.AMOUNT_ANOMALY: 0.14,
    FraudScenario.NEW_ACCOUNT_ABUSE: 0.06,
    FraudScenario.QUIET_FRAUD: 0.22,
}


@dataclass(slots=True)
class UserProfile:
    """Поведенческий профиль клиента — основа правдоподобия датасета."""

    user_id: str
    home_country: str
    home_latitude: float
    home_longitude: float
    avg_amount: float
    amount_std: float
    devices: list[str]
    ip_prefix: str
    typical_daily_frequency: float
    account_opened_at: datetime
    favourite_merchants: list[str]

    def account_age_days(self, at: datetime) -> int:
        return max(0, (at - self.account_opened_at).days)


@dataclass(slots=True)
class _TimelineState:
    """Состояние ленты клиента: то, что «помнит» система о прошлом."""

    previous_amount: float
    previous_country: str
    previous_latitude: float
    previous_longitude: float
    previous_ip: str
    previous_timestamp: datetime
    recent_timestamps: list[datetime] = field(default_factory=list)
    known_devices: list[str] = field(default_factory=list)
    # Текущая поездка: страна, сколько транзакций в ней осталось и локальная
    # IP-подсеть. Подсеть обязательна: клиент за границей физически не может
    # оставаться в домашней сети провайдера. Без этого модель отличала бы
    # поездку от фрода по IP, а не по поведению.
    trip_country: str | None = None
    trip_remaining: int = 0
    trip_ip_prefix: str | None = None


# ------------------------------------------------------------------ helpers


def _weighted_choice(rng: random.Random, weights: dict) -> object:
    """Выбор ключа словаря пропорционально весам."""
    keys = list(weights.keys())
    values = [weights[key] for key in keys]
    return rng.choices(keys, weights=values, k=1)[0]


def _datacenter_prefix(rng: random.Random) -> str:
    """Три октета внутри диапазона, который прототип считает VPN/хостингом."""
    return f"{rng.choice(DATACENTER_PREFIXES)}.{rng.randint(0, 255)}"


#: Доля мошеннических эпизодов, идущих через VPN, прокси или хостинг.
#: Не единица намеренно: идеальный разделитель в обучении даёт модель,
#: которая на настоящих данных разваливается о первого честного клиента
#: с корпоративным VPN.
ATTACKER_VPN_SHARE = 0.55

#: Доля обычных операций из тех же диапазонов. Меньше, чем у атак,
#: но заметно больше нуля — иначе признак стал бы меткой «это фрод».
LEGIT_VPN_SHARE = 0.03

#: Доля эпизодов фрода, приходящихся на кольца — счета под одним
#: оператором, работающие с одного устройства и из одной сети.
#:
#: Раньше каждый эпизод получал своё устройство, и на 99 360 строк
#: приходилось ровно два общих устройства — оба случайные совпадения
#: номеров. Граф связей, построенный ровно под этот паттерн, находить
#: ему было нечего, и панель показывала нули при любом размере потока.
#:
#: Десятая часть — не догадка о рынке, а замер. Поток берёт случайные
#: пятьсот строк из десяти тысяч, и кольцо видно, только если в выборку
#: попали двое из него. При этой доле кольцо находилось в 20 прогонах
#: из 20; при вдвое меньшей плотности — ни в одном. Меньшинством кольца
#: при этом остаются: большинство карточного фрода по-прежнему одиночное.
RING_EPISODE_SHARE = 0.10

#: Сколько счетов в одном кольце. Двух мало — пара клиентов на одном
#: устройстве бывает и по-честному (семья, один телефон на двоих),
#: и граф такую связь объясняет слишком легко. От трёх уже нет.
RING_SIZE_RANGE = (3, 5)


@dataclass(frozen=True, slots=True)
class AttackerIdentity:
    """Устройство и сеть, общие для нескольких эпизодов одного кольца."""

    device: str
    ip_prefix: str

def _random_ip_prefix(rng: random.Random) -> str:
    """Первые три октета IP — условная подсеть провайдера клиента."""
    return f"{rng.randint(37, 212)}.{rng.randint(0, 255)}.{rng.randint(0, 255)}"


def _ip_in_prefix(rng: random.Random, prefix: str) -> str:
    return f"{prefix}.{rng.randint(1, 254)}"


def _jitter_coordinates(
    rng: random.Random,
    latitude: float,
    longitude: float,
    spread_deg: float = 0.25,
) -> tuple[float, float]:
    """Разброс вокруг города: транзакции клиента происходят не в одной точке."""
    return (
        round(latitude + rng.uniform(-spread_deg, spread_deg), 6),
        round(longitude + rng.uniform(-spread_deg, spread_deg), 6),
    )


def _realistic_hour(rng: random.Random) -> int:
    """Час суток с дневным пиком: ночью платят заметно реже."""
    hour_weights = [
        1, 1, 1, 1, 1, 2,        # 00:00–05:59 — минимум
        4, 7, 9, 10, 11, 12,     # утро и обед
        12, 11, 10, 10, 11, 12,  # день
        11, 9, 7, 5, 3, 2,       # вечер и ночь
    ]
    return rng.choices(range(24), weights=hour_weights, k=1)[0]


def _night_hour(rng: random.Random) -> int:
    """Ночной час — типичное время автоматизированных атак."""
    return rng.choice([0, 1, 2, 3, 4, 5])


def _lognormal_amount(rng: random.Random, mean: float, std: float) -> float:
    """Сумма покупки: распределение с тяжёлым правым хвостом."""
    value = rng.lognormvariate(0.0, max(0.05, std / max(mean, 1.0)))
    return round(max(0.5, mean * value), 2)


# ------------------------------------------------------------------ profiles


def generate_user_profiles(
    count: int,
    rng: random.Random,
    end_date: datetime = DEFAULT_END_DATE,
) -> list[UserProfile]:
    """Создать `count` профилей клиентов."""
    profiles: list[UserProfile] = []

    for index in range(count):
        home_country = str(_weighted_choice(rng, HOME_COUNTRY_WEIGHTS))
        home_lat, home_lon = country_coordinates(home_country)
        home_lat, home_lon = _jitter_coordinates(rng, home_lat, home_lon, spread_deg=0.4)

        # Обычная сумма клиента: от экономного до премиального сегмента.
        avg_amount = round(rng.lognormvariate(3.9, 0.75), 2)  # медиана ~50 USD
        avg_amount = min(max(avg_amount, 8.0), 900.0)

        # 12 % клиентов открыли счёт недавно — нужны для сценария new_account_abuse.
        age_days = rng.randint(3, 60) if rng.random() < 0.12 else rng.randint(90, 3000)

        device_count = rng.choices([1, 2, 3], weights=[0.45, 0.40, 0.15], k=1)[0]
        devices = [f"dev_{index:05d}_{d}" for d in range(device_count)]

        favourites = rng.sample(EVERYDAY_MERCHANTS, k=rng.randint(3, 6))
        # Значительная часть клиентов законно пользуется «рискованными»
        # категориями: снятие наличных, переводы, крипта, ставки.
        # Без этого категория мерчанта становится прямой уликой фрода,
        # модель выучивает её и перестаёт смотреть на поведение.
        if rng.random() < 0.55:
            favourites.append("ATM Withdrawal")
        if rng.random() < 0.40:
            favourites.append(rng.choice(CASHOUT_MERCHANTS))

        profiles.append(
            UserProfile(
                user_id=f"user_{index:05d}",
                home_country=home_country,
                home_latitude=home_lat,
                home_longitude=home_lon,
                avg_amount=avg_amount,
                amount_std=round(avg_amount * rng.uniform(0.25, 0.85), 2),
                devices=devices,
                ip_prefix=_random_ip_prefix(rng),
                typical_daily_frequency=round(rng.uniform(0.7, 6.0), 2),
                account_opened_at=end_date - timedelta(days=age_days),
                favourite_merchants=favourites,
            )
        )

    return profiles


# -------------------------------------------------------------- transactions


def _count_recent(state: _TimelineState, now: datetime, hours: int) -> int:
    """Сколько транзакций клиента попало в окно последних `hours` часов."""
    threshold = now - timedelta(hours=hours)
    return sum(1 for ts in state.recent_timestamps if ts >= threshold)


def _build_row(
    profile: UserProfile,
    state: _TimelineState,
    *,
    transaction_index: int,
    timestamp: datetime,
    amount: float,
    merchant: str,
    country: str,
    device_id: str,
    ip_address: str,
    latitude: float,
    longitude: float,
    is_fraud: int,
    scenario: FraudScenario,
) -> dict:
    """Собрать строку датасета и обновить состояние ленты клиента."""
    state.recent_timestamps.append(timestamp)
    # Храним только последние сутки — окно для подсчёта частоты.
    cutoff = timestamp - timedelta(hours=24)
    state.recent_timestamps = [ts for ts in state.recent_timestamps if ts >= cutoff]

    count_24h = len(state.recent_timestamps)
    count_1h = _count_recent(state, timestamp, hours=1)

    row = {
        "transaction_id": f"txn_{profile.user_id}_{transaction_index:04d}",
        "user_id": profile.user_id,
        "timestamp": timestamp,
        "amount": round(amount, 2),
        "merchant": merchant,
        "merchant_category": MERCHANT_CATEGORY[merchant],
        "country": country,
        "device_id": device_id,
        "ip_address": ip_address,
        "latitude": latitude,
        "longitude": longitude,
        "transaction_frequency": count_24h,
        "previous_transaction_amount": round(state.previous_amount, 2),
        "previous_transaction_country": state.previous_country,
        "account_age_days": profile.account_age_days(timestamp),
        # --- контекст клиента: то, что в проде пришло бы из профильного хранилища
        "user_avg_amount": profile.avg_amount,
        "user_amount_std": profile.amount_std,
        "user_home_country": profile.home_country,
        "user_typical_frequency": profile.typical_daily_frequency,
        "known_device_ids": "|".join(state.known_devices),
        "previous_ip_address": state.previous_ip,
        "previous_timestamp": state.previous_timestamp,
        "previous_latitude": state.previous_latitude,
        "previous_longitude": state.previous_longitude,
        "txn_count_last_hour": count_1h,
        "txn_count_last_24h": count_24h,
        # --- целевая переменная
        "is_fraud": is_fraud,
        "fraud_scenario": scenario.value,
    }

    # Состояние «предыдущей транзакции» обновляем ПОСЛЕ формирования строки.
    state.previous_amount = amount
    state.previous_country = country
    state.previous_latitude = latitude
    state.previous_longitude = longitude
    state.previous_ip = ip_address
    state.previous_timestamp = timestamp
    if device_id not in state.known_devices:
        state.known_devices.append(device_id)

    return row


# Крейсерская скорость с учётом аэропорта и трансфера. Медленнее порога
# `MAX_PLAUSIBLE_SPEED_KMH` из features/geo.py намеренно: генератор должен
# создавать заведомо достижимые перемещения, а не пограничные.
TRAVEL_SPEED_KMH = 800.0
TRAVEL_OVERHEAD_HOURS = 1.5


def _can_physically_reach(
    state: _TimelineState,
    timestamp: datetime,
    latitude: float,
    longitude: float,
) -> bool:
    """Успел ли клиент физически добраться до точки к этому моменту.

    Без этой проверки поездка начиналась мгновенно: транзакция в Астане,
    через три часа — во Франкфурте. Признак `is_impossible_travel`
    срабатывал у добросовестных клиентов, и правило Risk Engine блокировало
    обычные поездки.
    """
    distance = haversine_km(
        state.previous_latitude, state.previous_longitude, latitude, longitude
    )
    if distance < 50.0:
        return True

    elapsed_hours = (timestamp - state.previous_timestamp).total_seconds() / 3600.0
    required_hours = distance / TRAVEL_SPEED_KMH + TRAVEL_OVERHEAD_HOURS
    return elapsed_hours >= required_hours


def _legit_transaction(
    profile: UserProfile,
    state: _TimelineState,
    rng: random.Random,
    *,
    transaction_index: int,
    timestamp: datetime,
    ring: AttackerIdentity | None = None,
) -> dict:
    """Легальная транзакция — с намеренными обманками-аномалиями."""
    # --- поездка: держится несколько транзакций подряд.
    # Любая смена локации проверяется на физическую достижимость: клиент не
    # может оказаться на другом континенте раньше, чем туда летит самолёт.
    home_lat, home_lon = _jitter_coordinates(
        rng, profile.home_latitude, profile.home_longitude, spread_deg=0.2
    )

    if state.trip_remaining > 0:
        # Клиент уже в поездке — остаётся там.
        country = state.trip_country or profile.home_country
        base_lat, base_lon = country_coordinates(country)
        latitude, longitude = _jitter_coordinates(rng, base_lat, base_lon, spread_deg=0.3)
        state.trip_remaining -= 1

    elif state.trip_country is not None:
        # Поездка закончилась: возвращаемся домой, но только если успели долететь.
        if _can_physically_reach(state, timestamp, home_lat, home_lon):
            country = profile.home_country
            latitude, longitude = home_lat, home_lon
            state.trip_country = None
            state.trip_ip_prefix = None
        else:
            country = state.trip_country
            base_lat, base_lon = country_coordinates(country)
            latitude, longitude = _jitter_coordinates(rng, base_lat, base_lon, spread_deg=0.3)

    elif rng.random() < 0.02:
        # Начало поездки. Часть поездок — в страны из списка повышенного риска
        # (командировки, диаспора): без этого `is_high_risk_country` был бы
        # тождественно нулём у легальных клиентов и стал бы безошибочной уликой.
        if rng.random() < 0.12:
            candidate = rng.choice(HIGH_RISK_COUNTRY_LIST)
        else:
            candidate = rng.choice(COMMON_TRAVEL_COUNTRIES)
        base_lat, base_lon = country_coordinates(candidate)
        candidate_lat, candidate_lon = _jitter_coordinates(rng, base_lat, base_lon, spread_deg=0.3)

        if _can_physically_reach(state, timestamp, candidate_lat, candidate_lon):
            country = candidate
            latitude, longitude = candidate_lat, candidate_lon
            state.trip_country = country
            state.trip_remaining = rng.randint(2, 6)
            state.trip_ip_prefix = _random_ip_prefix(rng)
        else:
            # Долететь не успел бы — остаётся дома.
            country = profile.home_country
            latitude, longitude = home_lat, home_lon
    else:
        country = profile.home_country
        latitude, longitude = home_lat, home_lon

    # --- устройство: иногда клиент законно покупает новый телефон
    if rng.random() < 0.03:
        device_id = f"{profile.user_id}_new_{rng.randint(100, 999)}"
        profile.devices.append(device_id)
    else:
        device_id = rng.choice(profile.devices)

    # --- IP: в поездке это местная сеть, дома — свой провайдер,
    # изредка — смена провайдера или мобильный интернет
    if state.trip_ip_prefix is not None:
        ip_address = _ip_in_prefix(rng, state.trip_ip_prefix)
    elif rng.random() < LEGIT_VPN_SHARE:
        # Честные клиенты тоже пользуются VPN: корпоративный доступ,
        # осторожность, обход блокировок в поездке. Без них признак
        # оказался бы идеальным разделителем, которого в жизни нет.
        ip_address = _ip_in_prefix(rng, _datacenter_prefix(rng))
    elif rng.random() < 0.04:
        ip_address = _ip_in_prefix(rng, _random_ip_prefix(rng))
    else:
        ip_address = _ip_in_prefix(rng, profile.ip_prefix)

    # --- счёт из кольца работает с устройства и из сети оператора
    #
    # Не только в эпизоде атаки, а в обычном трафике тоже: это счета,
    # которыми управляет один человек, а не жертвы, которых взломали
    # на один вечер. Поодиночке их операции безупречны — обычная сумма,
    # родная страна, знакомое устройство, — и ни одна политика на них
    # не срабатывает. Связь видна только на графе, и ради этого случая
    # граф и построен.
    #
    # Подмена, а не отдельный розыгрыш: последний октет берётся уже
    # разыгранный, и поток случайных чисел не сдвигается. В пересозданном
    # датасете меняются ровно строки колец — правку можно проверить
    # разностью файлов, а не доверием.
    if ring is not None:
        device_id = ring.device
        ip_address = f"{ring.ip_prefix}.{ip_address.rsplit('.', 1)[1]}"

    # --- сумма и мерчант
    roll = rng.random()
    if roll < 0.03:
        # Крупная законная покупка: техника, авиабилеты. Множитель намеренно
        # ниже, чем у сценария amount_anomaly: иначе крупная сумма становится
        # свидетельством в пользу легальности, и требование ТЗ §9.4
        # «большая сумма -> повышенный риск» перестаёт выполняться.
        amount = _lognormal_amount(rng, profile.avg_amount * rng.uniform(3.0, 15.0), profile.amount_std)
        merchant = rng.choice(BIG_TICKET_MERCHANTS)
    elif roll < 0.14:
        # Мелкая повседневная трата: кофе, такси, подписка. Нужна, чтобы
        # маленькая сумма сама по себе не была уликой прозвона карты.
        amount = round(rng.uniform(1.0, 12.0), 2)
        merchant = rng.choice(SMALL_TICKET_MERCHANTS)
    else:
        amount = _lognormal_amount(rng, profile.avg_amount, profile.amount_std)
        merchant = (
            rng.choice(profile.favourite_merchants)
            if rng.random() < 0.70
            else rng.choice(ALL_MERCHANTS)
        )

    return _build_row(
        profile,
        state,
        transaction_index=transaction_index,
        timestamp=timestamp,
        amount=amount,
        merchant=merchant,
        country=country,
        device_id=device_id,
        ip_address=ip_address,
        latitude=latitude,
        longitude=longitude,
        is_fraud=0,
        scenario=FraudScenario.NONE,
    )


def _fraud_merchant(rng: random.Random, cashout_probability: float) -> str:
    """Мерчант для мошеннической операции.

    Атакующий далеко не всегда идёт в «рискованную» категорию: часть операций
    проходит по обычным мерчантам. Если этого не сделать, категория мерчанта
    становится почти детерминированной уликой и модель опирается на неё вместо
    поведенческих признаков.
    """
    if rng.random() < cashout_probability:
        return rng.choice(CASHOUT_MERCHANTS)
    return rng.choice(EVERYDAY_MERCHANTS)


def _fraud_episode(
    profile: UserProfile,
    state: _TimelineState,
    rng: random.Random,
    *,
    scenario: FraudScenario,
    episode_length: int,
    start_index: int,
    start_time: datetime,
    ring: AttackerIdentity | None = None,
) -> tuple[list[dict], datetime]:
    """Сгенерировать эпизод фрода. Возвращает строки и время последней из них."""
    rows: list[dict] = []
    timestamp = start_time

    # Атакующий почти всегда работает со своего устройства и своей сети.
    attacker_device = f"dev_attacker_{rng.randint(10000, 99999)}"
    # Атакующий прячется за VPN чаще обычного человека, но не всегда:
    # бывает и взломанный домашний роутер, и мобильный интернет.
    # Доля намеренно не единица — иначе признак стал бы безошибочной
    # меткой фрода, модель оперлась бы на него одного, а на настоящих
    # данных, где VPN есть и у честных клиентов, это развалилось бы.
    attacker_ip_prefix = (
        _datacenter_prefix(rng) if rng.random() < ATTACKER_VPN_SHARE else _random_ip_prefix(rng)
    )

    # Кольцо подменяет разыгранные значения, а не заменяет сам розыгрыш.
    #
    # Выглядит лишней работой, но именно это делает правку проверяемой:
    # поток случайных чисел не сдвигается, и в пересозданном датасете
    # меняются ровно те строки, которые вошли в кольца. Пропусти мы
    # два вызова rng — сдвинулось бы всё до конца ленты, и отличить
    # «появились кольца» от «данные другие» стало бы нечем.
    if ring is not None:
        attacker_device = ring.device
        attacker_ip_prefix = ring.ip_prefix

    for step in range(episode_length):
        if scenario is FraudScenario.ACCOUNT_TAKEOVER:
            # Захват аккаунта не всегда выглядит одинаково: бывает и угон сессии
            # со знакомого устройства, и операция внутри домашней страны.
            if rng.random() < 0.70:
                country = rng.choice(HIGH_RISK_COUNTRY_LIST) if rng.random() < 0.6 else rng.choice(
                    [c for c in COUNTRY_COORDINATES if c != profile.home_country]
                )
            else:
                country = profile.home_country
            base_lat, base_lon = country_coordinates(country)
            latitude, longitude = _jitter_coordinates(rng, base_lat, base_lon, spread_deg=0.2)
            device_id = attacker_device if rng.random() < 0.75 else rng.choice(profile.devices)
            ip_address = _ip_in_prefix(rng, attacker_ip_prefix)
            amount = _lognormal_amount(rng, profile.avg_amount * rng.uniform(1.2, 8.0), profile.amount_std)
            merchant = _fraud_merchant(rng, 0.55)
            gap = timedelta(minutes=rng.randint(2, 25))

        elif scenario is FraudScenario.CARD_TESTING:
            # Прозвон карты: много мелких списаний подряд на одном мерчанте.
            country = profile.home_country if rng.random() < 0.4 else rng.choice(
                [c for c in COUNTRY_COORDINATES if c != profile.home_country]
            )
            base_lat, base_lon = country_coordinates(country)
            latitude, longitude = _jitter_coordinates(rng, base_lat, base_lon, spread_deg=0.1)
            device_id = attacker_device
            ip_address = _ip_in_prefix(rng, attacker_ip_prefix)
            amount = round(rng.uniform(0.8, 9.0), 2)
            merchant = CARD_TESTING_MERCHANTS[start_index % len(CARD_TESTING_MERCHANTS)]
            gap = timedelta(seconds=rng.randint(30, 180))

        elif scenario is FraudScenario.IMPOSSIBLE_TRAVEL:
            # Далёкая страна через считаные минуты после домашней транзакции.
            country = rng.choice(
                [c for c in ("BR", "US", "NG", "VE", "PH", "ID", "IN", "CN") if c != profile.home_country]
            )
            base_lat, base_lon = country_coordinates(country)
            latitude, longitude = _jitter_coordinates(rng, base_lat, base_lon, spread_deg=0.15)
            device_id = attacker_device if rng.random() < 0.7 else rng.choice(profile.devices)
            ip_address = _ip_in_prefix(rng, attacker_ip_prefix)
            amount = _lognormal_amount(rng, profile.avg_amount * rng.uniform(1.2, 5.0), profile.amount_std)
            merchant = _fraud_merchant(rng, 0.45)
            gap = timedelta(minutes=rng.randint(5, 45))

        elif scenario is FraudScenario.NEW_DEVICE_CASHOUT:
            # Вывод средств дома, но с незнакомого устройства.
            country = profile.home_country
            latitude, longitude = _jitter_coordinates(
                rng, profile.home_latitude, profile.home_longitude, spread_deg=0.3
            )
            device_id = attacker_device
            ip_address = _ip_in_prefix(rng, attacker_ip_prefix)
            amount = _lognormal_amount(rng, profile.avg_amount * rng.uniform(1.0, 8.0), profile.amount_std)
            merchant = _fraud_merchant(rng, 0.50)
            gap = timedelta(minutes=rng.randint(3, 40))

        elif scenario is FraudScenario.AMOUNT_ANOMALY:
            # Самый трудный случай: всё привычное, ненормальна только сумма.
            country = profile.home_country
            latitude, longitude = _jitter_coordinates(
                rng, profile.home_latitude, profile.home_longitude, spread_deg=0.2
            )
            device_id = rng.choice(profile.devices)
            ip_address = _ip_in_prefix(rng, profile.ip_prefix)
            amount = _lognormal_amount(rng, profile.avg_amount * rng.uniform(5.0, 25.0), profile.amount_std)
            merchant = _fraud_merchant(rng, 0.25)
            gap = timedelta(hours=rng.randint(1, 8))

        elif scenario is FraudScenario.QUIET_FRAUD:
            # Украденная карта используется осторожно: ровно ОДНА аномалия,
            # всё остальное неотличимо от обычного поведения клиента.
            # Без таких случаев модель учится, что фрод — это всегда несколько
            # сигналов сразу, и одиночная аномалия получает нулевой риск.
            # В реальности именно тихие случаи и порождают решение CHALLENGE.
            country = profile.home_country
            latitude, longitude = _jitter_coordinates(
                rng, profile.home_latitude, profile.home_longitude, spread_deg=0.25
            )
            device_id = rng.choice(profile.devices)
            ip_address = _ip_in_prefix(rng, profile.ip_prefix)
            amount = _lognormal_amount(rng, profile.avg_amount, profile.amount_std)
            merchant = rng.choice(profile.favourite_merchants)
            # Целые минуты: дробные часы дают микросекунды и делают
            # формат времени в CSV неоднородным.
            gap = timedelta(minutes=rng.randint(60, 600))

            anomaly = rng.choice(("device", "country", "amount"))
            if anomaly == "device":
                device_id = attacker_device
            elif anomaly == "country":
                country = rng.choice(COMMON_TRAVEL_COUNTRIES)
                base_lat, base_lon = country_coordinates(country)
                latitude, longitude = _jitter_coordinates(rng, base_lat, base_lon, spread_deg=0.2)
                ip_address = _ip_in_prefix(rng, attacker_ip_prefix)
            else:
                amount = _lognormal_amount(
                    rng, profile.avg_amount * rng.uniform(3.0, 8.0), profile.amount_std
                )

        else:  # FraudScenario.NEW_ACCOUNT_ABUSE
            country = profile.home_country if rng.random() < 0.5 else rng.choice(COMMON_TRAVEL_COUNTRIES)
            base_lat, base_lon = country_coordinates(country)
            latitude, longitude = _jitter_coordinates(rng, base_lat, base_lon, spread_deg=0.2)
            device_id = attacker_device
            ip_address = _ip_in_prefix(rng, attacker_ip_prefix)
            amount = _lognormal_amount(rng, profile.avg_amount * rng.uniform(2.5, 10.0), profile.amount_std)
            merchant = _fraud_merchant(rng, 0.60)
            gap = timedelta(minutes=rng.randint(10, 120))

        rows.append(
            _build_row(
                profile,
                state,
                transaction_index=start_index + step,
                timestamp=timestamp,
                amount=amount,
                merchant=merchant,
                country=country,
                device_id=device_id,
                ip_address=ip_address,
                latitude=latitude,
                longitude=longitude,
                is_fraud=1,
                scenario=scenario,
            )
        )
        timestamp = timestamp + gap

    return rows, timestamp


def _pick_scenario(profile: UserProfile, rng: random.Random, end_date: datetime) -> FraudScenario:
    """Выбрать сценарий атаки, допустимый для этого клиента.

    Злоупотребление новым счётом возможно только на молодом счёте, поэтому
    сценарий привязан к возрасту счёта напрямую, а не отбрасывается постфактум:
    иначе он выпадал бы настолько редко, что модель не смогла бы его выучить.
    """
    if profile.account_age_days(end_date) <= NEW_ACCOUNT_THRESHOLD_DAYS and rng.random() < 0.45:
        return FraudScenario.NEW_ACCOUNT_ABUSE

    weights = {
        scenario: weight
        for scenario, weight in SCENARIO_WEIGHTS.items()
        if scenario is not FraudScenario.NEW_ACCOUNT_ABUSE
    }
    scenario = _weighted_choice(rng, weights)
    assert isinstance(scenario, FraudScenario)
    return scenario


def _draw_timeline_timestamps(
    rng: random.Random,
    *,
    count: int,
    start_time: datetime,
    window_days: float,
) -> list[datetime]:
    """Отсортированные моменты транзакций внутри окна наблюдения.

    Время рисуется сразу целиком и сортируется, а не наращивается шагами.
    Это даёт три нужных свойства одновременно:
      * строгую монотонность ленты (иначе `previous_timestamp` мог бы оказаться
        позже текущей транзакции и все интервальные признаки сломались бы);
      * реалистичное распределение по часам суток (ночью платят реже);
      * гарантию, что лента не вылезает за правую границу окна.
    """
    timestamps: list[datetime] = []
    for _ in range(count):
        moment = start_time + timedelta(days=rng.uniform(0.0, window_days))
        timestamps.append(
            moment.replace(
                hour=_realistic_hour(rng),
                minute=rng.randint(0, 59),
                second=rng.randint(0, 59),
                microsecond=0,
            )
        )
    timestamps.sort()
    return timestamps


def _generate_user_timeline(
    profile: UserProfile,
    rng: random.Random,
    *,
    transaction_count: int,
    fraud_count: int,
    fraud_scenario: FraudScenario,
    window_days: float,
    end_date: datetime,
    ring: AttackerIdentity | None = None,
) -> list[dict]:
    """Хронологическая лента транзакций одного клиента."""
    # Окно ограничено и возрастом счёта: у вчерашнего клиента нет годовой истории.
    effective_window = max(2.0, min(window_days, float(profile.account_age_days(end_date))))
    # Микросекунды обнуляем: окно задаётся дробным числом дней, и без округления
    # в CSV попадает неоднородный формат времени, который потом не парсится.
    start_time = (end_date - timedelta(days=effective_window)).replace(microsecond=0)

    # Синтетическая «нулевая» транзакция: у первой реальной должен быть контекст.
    state = _TimelineState(
        previous_amount=profile.avg_amount,
        previous_country=profile.home_country,
        previous_latitude=profile.home_latitude,
        previous_longitude=profile.home_longitude,
        previous_ip=_ip_in_prefix(rng, profile.ip_prefix),
        previous_timestamp=start_time - timedelta(hours=12),
        known_devices=list(profile.devices),
    )

    # Рисуем моменты с запасом от правой границы: эпизод фрода добавит
    # собственные интервалы поверх момента старта.
    draw_window = max(1.0, effective_window - EPISODE_TIME_MARGIN_DAYS)
    timestamps = _draw_timeline_timestamps(
        rng, count=transaction_count, start_time=start_time, window_days=draw_window
    )

    # Эпизод начинается не в начале ленты (нужна история) и не в самом конце.
    if fraud_count > 0 and transaction_count > 6:
        fraud_start_index = rng.randint(
            max(3, transaction_count // 5), max(4, (transaction_count * 4) // 5)
        )
    else:
        fraud_start_index = -1

    scenario = fraud_scenario

    rows: list[dict] = []
    index = 0
    last_timestamp = state.previous_timestamp

    while index < transaction_count:
        if index == fraud_start_index:
            episode_start = timestamps[index]
            # Автоматизированные атаки чаще идут ночью.
            takeover_or_testing = scenario in (
                FraudScenario.ACCOUNT_TAKEOVER,
                FraudScenario.CARD_TESTING,
            )
            if takeover_or_testing and rng.random() < 0.65:
                episode_start = episode_start.replace(hour=_night_hour(rng))
            # Страховка монотонности после сдвига часа.
            if episode_start <= last_timestamp:
                episode_start = last_timestamp + timedelta(minutes=rng.randint(20, 180))

            episode_rows, last_timestamp = _fraud_episode(
                profile,
                state,
                rng,
                scenario=scenario,
                episode_length=min(fraud_count, transaction_count - index),
                start_index=index,
                start_time=episode_start,
                ring=ring,
            )
            rows.extend(episode_rows)
            index += len(episode_rows)
            continue

        # Легальная транзакция не может оказаться раньше уже выпущенной.
        timestamp = max(timestamps[index], last_timestamp + timedelta(seconds=30))
        rows.append(
            _legit_transaction(
                profile,
                state,
                rng,
                transaction_index=index,
                timestamp=timestamp,
                ring=ring,
            )
        )
        last_timestamp = timestamp
        index += 1

    return rows


# ------------------------------------------------------------------- public


def _plan_rings(
    fraud_plan: list[tuple[FraudScenario, int]],
    *,
    seed: int,
) -> list[AttackerIdentity | None]:
    """Раздать части эпизодов общее устройство и общую сеть.

    Кольцо — это несколько жертв, обработанных с одного устройства
    и из одной сети: дроповая сеть, скупленные учётки, один человек
    с базой украденных реквизитов. По одной операции такая связь
    не видна вовсе — видна она только на графе, и ради неё граф
    и существует.

    Свой генератор случайных чисел, а не общий, намеренно: этот
    розыгрыш добавлен позже остальных, и общий поток от него сдвинулся
    бы целиком. Зерно производное от основного — воспроизводимость
    сохраняется.
    """
    planner = random.Random(seed ^ 0x5249_4E47)  # 'RING'
    victims = [index for index, (_, length) in enumerate(fraud_plan) if length > 0]
    planner.shuffle(victims)

    rings: list[AttackerIdentity | None] = [None] * len(fraud_plan)
    in_rings = int(len(victims) * RING_EPISODE_SHARE)

    position = 0
    while position < in_rings:
        size = planner.randint(*RING_SIZE_RANGE)
        members = victims[position : position + size]
        # Кольцо из одного участника — не кольцо: хвост оставляем одиночкам.
        if len(members) < RING_SIZE_RANGE[0]:
            break
        identity = AttackerIdentity(
            device=f"dev_ring_{planner.randint(10000, 99999)}",
            # Сеть обычная, не дата-центр — в отличие от одиночной атаки.
            #
            # Кольцо живёт не набегом, а годами, и прячется не за VPN,
            # а за обыкновенностью: телефон, домашний или мобильный
            # интернет, привычные суммы. Дата-центровый адрес подсветил
            # бы весь его трафик признаком `is_vpn_ip` — и группа,
            # которую поодиночке не видно, стала бы видна по одной
            # операции. Тогда граф был бы не нужен, а сеть, которую
            # ловят по адресу, в жизни меняет адрес.
            ip_prefix=_random_ip_prefix(planner),
        )
        for index in members:
            rings[index] = identity
        position += len(members)

    return rings


def generate_dataset(
    rows: int = 100_000,
    users: int = 3_000,
    fraud_rate: float = 0.02,
    seed: int = 42,
    end_date: datetime = DEFAULT_END_DATE,
) -> pd.DataFrame:
    """Сгенерировать датасет транзакций.

    Args:
        rows: примерное количество транзакций.
        users: количество профилей клиентов.
        fraud_rate: целевая доля мошеннических транзакций.
        seed: зерно генератора — обеспечивает воспроизводимость.
        end_date: правая граница временного окна выборки.

    Returns:
        DataFrame, отсортированный по времени, с колонкой `is_fraud`.
    """
    if rows <= 0 or users <= 0:
        raise ValueError("rows и users должны быть положительными")
    if not 0.0 < fraud_rate < 0.5:
        raise ValueError("fraud_rate должен быть в диапазоне (0, 0.5)")

    rng = random.Random(seed)
    profiles = generate_user_profiles(users, rng, end_date=end_date)

    # --- ширина окна наблюдения выводится из требуемого объёма и активности
    # клиентов, а не задаётся произвольно. Тогда `transaction_frequency`
    # в данных совпадает с обычной частотой клиента из профиля — иначе признак
    # «необычная частота» учился бы на несогласованных величинах.
    mean_frequency = sum(p.typical_daily_frequency for p in profiles) / len(profiles)
    window_days = rows / (users * mean_frequency)
    window_days = min(max(window_days, 7.0), float(DATASET_SPAN_DAYS))

    counts = [
        max(5, round(p.typical_daily_frequency * min(window_days, p.account_age_days(end_date))))
        for p in profiles
    ]
    # Точная подгонка под требуемый объём.
    scale = rows / max(1, sum(counts))
    counts = [max(5, round(count * scale)) for count in counts]

    # --- распределяем бюджет фрода по клиентам целыми эпизодами.
    # Сценарий и длина эпизода выбираются здесь ОДИН раз и вместе: длина
    # эпизода специфична для сценария (прозвон карты — это десяток мелких
    # списаний, а вывод с нового устройства — одна-две крупных операции).
    fraud_budget = int(rows * fraud_rate)
    fraud_plan: list[tuple[FraudScenario, int]] = [(FraudScenario.NONE, 0)] * len(profiles)
    candidates = [i for i, count in enumerate(counts) if count > 6]
    rng.shuffle(candidates)

    allocated = 0
    for user_index in candidates:
        if allocated >= fraud_budget:
            break
        scenario = _pick_scenario(profiles[user_index], rng, end_date)
        low, high = SCENARIO_EPISODE_LENGTH[scenario]
        episode_length = rng.randint(low, high)
        episode_length = min(episode_length, fraud_budget - allocated, counts[user_index] - 4)
        if episode_length <= 0:
            continue
        fraud_plan[user_index] = (scenario, episode_length)
        allocated += episode_length

    # --- часть эпизодов объединяем в кольца
    ring_plan = _plan_rings(fraud_plan, seed=seed)

    # --- генерация лент
    all_rows: list[dict] = []
    for profile, count, (scenario, fraud_count), ring in zip(
        profiles, counts, fraud_plan, ring_plan, strict=True
    ):
        all_rows.extend(
            _generate_user_timeline(
                profile,
                rng,
                transaction_count=count,
                fraud_count=fraud_count,
                fraud_scenario=scenario,
                window_days=window_days,
                end_date=end_date,
                ring=ring,
            )
        )

    frame = pd.DataFrame(all_rows)
    frame = frame.sort_values("timestamp").reset_index(drop=True)

    # Точная подгонка размера: обрезаем хвост, сохраняя хронологию.
    if len(frame) > rows:
        frame = frame.head(rows).reset_index(drop=True)

    return frame


REQUIRED_COLUMNS: tuple[str, ...] = (
    "transaction_id", "user_id", "timestamp", "amount", "merchant", "country",
    "device_id", "ip_address", "latitude", "longitude", "transaction_frequency",
    "previous_transaction_amount", "previous_transaction_country", "account_age_days",
    "is_fraud",
)


def validate_dataset(frame: pd.DataFrame, end_date: datetime = DEFAULT_END_DATE) -> list[str]:
    """Проверить внутреннюю согласованность датасета.

    Возвращает список проблем; пустой список означает, что данные корректны.
    Проверки нужны потому, что ошибки генерации (нарушенная хронология,
    рассинхронизация previous_*) выглядят в CSV безобидно, но делают
    поведенческие признаки бессмысленными.
    """
    problems: list[str] = []

    missing = [column for column in REQUIRED_COLUMNS if column not in frame.columns]
    if missing:
        problems.append(f"отсутствуют обязательные колонки: {missing}")
        return problems

    nulls = frame[list(REQUIRED_COLUMNS)].isna().sum()
    for column, count in nulls.items():
        if count:
            problems.append(f"колонка {column}: {count} пустых значений")

    if (frame["amount"] <= 0).any():
        problems.append("есть транзакции с неположительной суммой")

    if frame["transaction_id"].duplicated().any():
        problems.append("transaction_id не уникален")

    # Предыдущая транзакция обязана быть строго раньше текущей.
    non_monotonic = (frame["previous_timestamp"] >= frame["timestamp"]).sum()
    if non_monotonic:
        problems.append(f"нарушена хронология previous_timestamp >= timestamp: {non_monotonic} строк")

    # previous_* должны совпадать с реальной предыдущей транзакцией клиента.
    ordered = frame.sort_values(["user_id", "timestamp"])
    expected_previous = ordered.groupby("user_id", observed=True)["amount"].shift(1)
    actual_previous = ordered["previous_transaction_amount"]
    mismatch = ((expected_previous - actual_previous).abs() > 0.011).sum()
    if mismatch:
        problems.append(f"previous_transaction_amount расходится с лентой клиента: {mismatch} строк")

    if frame["timestamp"].max() > end_date:
        problems.append(f"есть транзакции позже правой границы окна {end_date}")

    fraud_rate = float(frame["is_fraud"].mean())
    if not 0.005 <= fraud_rate <= 0.06:
        problems.append(f"доля фрода вне разумного диапазона: {fraud_rate:.3%}")

    if frame["is_fraud"].nunique() < 2:
        problems.append("в датасете представлен только один класс")

    return problems


def dataset_summary(frame: pd.DataFrame) -> dict:
    """Краткая сводка по датасету — печатается после генерации."""
    fraud = frame[frame["is_fraud"] == 1]
    legit = frame[frame["is_fraud"] == 0]

    scenario_counts = (
        fraud["fraud_scenario"].value_counts().to_dict() if not fraud.empty else {}
    )

    return {
        "rows": len(frame),
        "users": int(frame["user_id"].nunique()),
        "fraud_rows": len(fraud),
        "fraud_rate": round(float(len(fraud) / len(frame)), 5) if len(frame) else 0.0,
        "date_from": str(frame["timestamp"].min()),
        "date_to": str(frame["timestamp"].max()),
        "countries": int(frame["country"].nunique()),
        "merchants": int(frame["merchant"].nunique()),
        "avg_amount_legit": round(float(legit["amount"].mean()), 2) if not legit.empty else 0.0,
        "avg_amount_fraud": round(float(fraud["amount"].mean()), 2) if not fraud.empty else 0.0,
        "scenarios": scenario_counts,
    }
