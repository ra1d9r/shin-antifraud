"""Готовые сценарии ручного тестирования (ТЗ §9).

Пять сценариев из ТЗ описаны здесь данными, а не разбросаны по документации
и тестам. Один источник правды даёт три вещи сразу: их можно прогнать через
Swagger одним запросом, подставить кнопкой в симуляторе (этап 11) и проверить
автотестом.

## Два принципа, без которых сценарии бесполезны

**Общий профиль клиента.** Все пять описывают одного и того же человека:
обычная сумма 100, дом — Казахстан, два известных устройства, три операции
в сутки, счёту 800 дней. Меняется ровно то, что заявлено в названии
сценария. Иначе сравнивать Risk Score между ними бессмысленно.

**Явный контекст и фиксированное время.** Профиль передаётся в каждом
запросе целиком, а метки времени заданы абсолютными значениями. Поэтому
результат не зависит ни от накопленной истории, ни от того, в котором часу
запускают демонстрацию: числа в документации воспроизводятся всегда.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.schemas.enums import ScenarioKey
from app.schemas.transaction import TransactionRequest

# Опорное время демонстрации: вторник, будний день, 14:30 — обычное время покупок.
DEMO_TIME = datetime(2026, 9, 1, 14, 30, 0)
# Ночь для сценария с атакой: автоматизированный фрод чаще идёт ночью.
DEMO_NIGHT = datetime(2026, 9, 1, 2, 14, 0)

# Домашние координаты клиента — Астана.
HOME_LATITUDE = 51.16
HOME_LONGITUDE = 71.44

# Лагос: используется в сценариях с чужой страной.
LAGOS_LATITUDE = 6.5244
LAGOS_LONGITUDE = 3.3792


def _base(timestamp: datetime = DEMO_TIME, **overrides) -> dict:
    """Обычная транзакция знакомого клиента — основа всех сценариев."""
    body = {
        "user_id": "user_demo",
        "amount": 100.0,
        "timestamp": timestamp.isoformat(),
        "merchant": "Magnum",
        "country": "KZ",
        "device_id": "dev_known_1",
        "ip_address": "85.132.10.55",
        "latitude": HOME_LATITUDE,
        "longitude": HOME_LONGITUDE,
        "transaction_frequency": 3,
        "previous_transaction_amount": 95.0,
        "previous_transaction_country": "KZ",
        "account_age_days": 800,
        # --- профиль клиента передаётся явно: результат обязан быть
        # воспроизводимым независимо от накопленной истории
        "user_avg_amount": 100.0,
        "user_amount_std": 30.0,
        "user_home_country": "KZ",
        "user_typical_frequency": 3.0,
        "known_device_ids": ["dev_known_1", "dev_known_2"],
        "previous_ip_address": "85.132.10.40",
        "previous_timestamp": (timestamp - timedelta(hours=5)).isoformat(),
        "previous_latitude": 51.15,
        "previous_longitude": 71.40,
        "txn_count_last_hour": 1,
        "merchant_category": "grocery",
    }
    body.update(overrides)
    return body


@dataclass(frozen=True, slots=True)
class Scenario:
    """Один сценарий ручного тестирования."""

    key: ScenarioKey
    title: str
    description: str
    expectation: str
    changed_from_normal: tuple[str, ...]
    request: dict

    def to_transaction(self) -> TransactionRequest:
        return TransactionRequest(**self.request)


SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        key=ScenarioKey.NORMAL,
        title="Normal transaction",
        description=(
            "Обычная покупка в продуктовом: привычная сумма, знакомое устройство, "
            "домашняя страна, нормальная частота операций."
        ),
        expectation="низкий Risk Score, решение APPROVE",
        changed_from_normal=(),
        request=_base(),
    ),
    Scenario(
        key=ScenarioKey.NEW_DEVICE,
        title="New device",
        description=(
            "Та же покупка, но с незнакомого устройства и из незнакомой сети. "
            "Именно такая пара сигналов — сигнатура входа злоумышленника; "
            "новый телефон в домашней сети система намеренно не считает "
            "поводом для проверки."
        ),
        expectation="Risk Score заметно выше, чем в сценарии 1",
        changed_from_normal=("device_id", "ip_address"),
        request=_base(device_id="dev_unknown_77", ip_address="203.0.113.7"),
    ),
    Scenario(
        key=ScenarioKey.UNUSUAL_COUNTRY,
        title="Unusual country",
        description=(
            "Клиент обычно платит из Казахстана, а операция идёт из Нигерии. "
            "Прошло 20 часов — долететь можно, так что невозможного перемещения "
            "здесь нет. IP местный: человек физически находится в другой стране."
        ),
        expectation="повышенный риск",
        changed_from_normal=("country", "latitude", "longitude", "ip_address", "previous_timestamp"),
        request=_base(
            country="NG",
            latitude=LAGOS_LATITUDE,
            longitude=LAGOS_LONGITUDE,
            ip_address="197.210.44.12",
            previous_timestamp=(DEMO_TIME - timedelta(hours=20)).isoformat(),
        ),
    ),
    Scenario(
        key=ScenarioKey.LARGE_AMOUNT,
        title="Large amount",
        description=(
            "Сумма в 25 раз выше обычной для клиента. Всё остальное привычно: "
            "своё устройство, домашняя страна, своя сеть."
        ),
        expectation="повышенный риск",
        changed_from_normal=("amount",),
        request=_base(amount=2500.0),
    ),
    Scenario(
        key=ScenarioKey.MULTIPLE_ANOMALIES,
        title="Multiple anomalies",
        description=(
            "Захват аккаунта ночью: крупная сумма, незнакомое устройство и сеть, "
            "чужая страна повышенного риска, всплеск частоты операций и "
            "физически невозможное перемещение — операция в Нигерии через "
            "22 минуты после операции в Казахстане."
        ),
        expectation="высокий Risk Score, решение BLOCK",
        changed_from_normal=(
            "amount", "device_id", "ip_address", "country", "latitude", "longitude",
            "transaction_frequency", "txn_count_last_hour", "merchant", "timestamp",
        ),
        request=_base(
            timestamp=DEMO_NIGHT,
            amount=3000.0,
            device_id="dev_attacker_01",
            ip_address="203.0.113.7",
            country="NG",
            latitude=LAGOS_LATITUDE,
            longitude=LAGOS_LONGITUDE,
            merchant="Binance",
            merchant_category="crypto",
            transaction_frequency=25,
            txn_count_last_hour=12,
            previous_timestamp=(DEMO_NIGHT - timedelta(minutes=22)).isoformat(),
        ),
    ),
)

_BY_KEY: dict[ScenarioKey, Scenario] = {scenario.key: scenario for scenario in SCENARIOS}


def get_scenario(key: ScenarioKey) -> Scenario:
    """Сценарий по ключу."""
    try:
        return _BY_KEY[key]
    except KeyError as exc:  # pragma: no cover — ключ валидируется FastAPI
        raise KeyError(f"Неизвестный сценарий: {key}") from exc


def scenario_order() -> tuple[ScenarioKey, ...]:
    """Порядок сценариев в ТЗ §9 — от безобидного к явной атаке."""
    return tuple(scenario.key for scenario in SCENARIOS)
