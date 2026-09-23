"""Тесты хранилищ (ТЗ §2.1, решение D-4).

Профиль клиента — источник признаков «отклонение от обычного поведения».
Ошибка здесь не падает с исключением, а тихо портит вход модели, поэтому
свойства профиля проверяются числами, а не фактом работы.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.schemas.enums import Decision, RiskLevel
from app.store.profiles import FREQUENCY_WINDOW_HOURS, MAX_KNOWN_DEVICES, UserProfileStore
from app.store.transactions import TransactionRecord, TransactionStore

BASE = datetime(2026, 9, 1, 12, 0, 0)


def record(store: UserProfileStore, user: str = "u", **overrides) -> None:
    payload = {
        "amount": 100.0,
        "country": "KZ",
        "device_id": "dev_1",
        "ip_address": "85.1.2.3",
        "timestamp": BASE,
        "latitude": 51.0,
        "longitude": 71.0,
    }
    payload.update(overrides)
    store.record(user, **payload)


# --------------------------------------------------------------- профиль


def test_profile_accumulates_devices_and_countries() -> None:
    store = UserProfileStore()
    record(store, device_id="dev_1", country="KZ")
    record(store, device_id="dev_2", country="KZ", timestamp=BASE + timedelta(hours=1))
    record(store, device_id="dev_1", country="DE", timestamp=BASE + timedelta(hours=2))

    profile = store.get("u")
    assert profile.known_devices == ["dev_1", "dev_2"]
    assert profile.transaction_count == 3
    assert profile.dominant_country == "KZ"


def test_known_devices_list_is_bounded() -> None:
    """Без ограничения «известным» со временем станет любое устройство."""
    store = UserProfileStore()
    for index in range(MAX_KNOWN_DEVICES + 5):
        record(store, device_id=f"dev_{index}", timestamp=BASE + timedelta(minutes=index))

    assert len(store.get("u").known_devices) == MAX_KNOWN_DEVICES


def test_average_and_std_are_computed() -> None:
    store = UserProfileStore()
    for amount in (100.0, 200.0, 300.0):
        record(store, amount=amount)

    profile = store.get("u")
    assert profile.average_amount == pytest.approx(200.0)
    assert profile.amount_std == pytest.approx(81.65, abs=0.1)


def test_unknown_user_has_no_profile() -> None:
    assert UserProfileStore().get("nobody") is None


# ------------------------------------------------- регрессии на дефекты


def test_typical_frequency_matches_the_counting_window() -> None:
    """Регрессия: частота считалась как (операции за всё время) / (окно 24 ч).

    `transaction_count` растёт за всё время жизни профиля, а
    `recent_timestamps` обрезается сутками. Деление одного на другое
    давало завышение в десятки раз: у клиента с месячной историей
    выходило 114 операций в сутки вместо 3.4, и признак `frequency_ratio`
    переставал что-либо значить.
    """
    store = UserProfileStore()
    # Месяц истории с шагом 7 часов — это 3.43 операции в сутки.
    for index in range(100):
        record(store, timestamp=BASE + timedelta(hours=index * 7))

    profile = store.get("u")
    assert profile.transaction_count == 100
    assert len(profile.recent_timestamps) < 10, "окно должно быть обрезано сутками"

    frequency = profile.typical_daily_frequency
    assert frequency is not None
    assert frequency < 12, f"частота {frequency:.1f} завышена — снова делим на чужое окно"


def test_window_is_pruned_relative_to_latest_transaction() -> None:
    """Регрессия: обрезка велась по времени входящей операции.

    Симулятор позволяет задать любое время, поэтому транзакции приходят
    не по порядку. Отсчёт от входящей метки означал, что одна операция
    «из прошлого» отменяет обрезку и окно растёт без границ.
    """
    store = UserProfileStore()
    for offset_hours in (0, 50, 1, 60):
        record(store, timestamp=BASE + timedelta(hours=offset_hours))

    kept = store.get("u").recent_timestamps
    latest = BASE + timedelta(hours=60)
    assert all(moment >= latest - timedelta(hours=FREQUENCY_WINDOW_HOURS) for moment in kept)
    assert len(kept) == 2, f"в окне должны остаться только часы 50 и 60, осталось {len(kept)}"


def test_frequency_is_undefined_on_short_history() -> None:
    """Лучше вернуть None, чем выдумать частоту по одной операции."""
    store = UserProfileStore()
    record(store)
    assert store.get("u").typical_daily_frequency is None


# ----------------------------------------------------------- транзакции


def make_record(**overrides) -> TransactionRecord:
    payload = {
        "transaction_id": "txn_1",
        "user_id": "u",
        "timestamp": BASE,
        "amount": 100.0,
        "country": "KZ",
        "merchant": "Magnum",
        "device_id": "dev_1",
        "risk_score": 10,
        "model_score": 10,
        "decision": Decision.APPROVE,
        "risk_level": RiskLevel.LOW,
        "triggered_rules": (),
        "top_reason": None,
    }
    payload.update(overrides)
    return TransactionRecord(**payload)


def test_store_is_a_bounded_ring_buffer() -> None:
    """Прототип работает без базы: неограниченный список съел бы память."""
    store = TransactionStore(capacity=3)
    for index in range(10):
        store.add(make_record(transaction_id=f"txn_{index}"))

    assert store.size() == 3
    assert store.processed_total == 10, "счётчик за всё время не должен обнуляться вытеснением"
    assert [item.transaction_id for item in store.all()] == ["txn_7", "txn_8", "txn_9"]


def test_store_rejects_invalid_capacity() -> None:
    with pytest.raises(ValueError):
        TransactionStore(capacity=0)


def test_query_returns_newest_first_and_filters() -> None:
    store = TransactionStore(capacity=10)
    store.add(make_record(transaction_id="a", decision=Decision.APPROVE, risk_score=5))
    store.add(make_record(transaction_id="b", decision=Decision.BLOCK, risk_score=95,
                          risk_level=RiskLevel.CRITICAL, country="NG"))

    total, items = store.query()
    assert total == 2
    assert [item.transaction_id for item in items] == ["b", "a"]

    total, items = store.query(decision=Decision.BLOCK)
    assert total == 1 and items[0].transaction_id == "b"

    total, _ = store.query(country="ng")
    assert total == 1, "фильтр по стране должен быть нечувствителен к регистру"

    total, _ = store.query(min_risk_score=50)
    assert total == 1


def test_statistics_on_empty_store() -> None:
    payload = TransactionStore().statistics()
    assert payload["total_transactions"] == 0
    assert payload["average_risk_score"] == 0.0
    assert payload["fraud_rate"] == 0.0


def test_statistics_count_decisions_and_rules() -> None:
    store = TransactionStore(capacity=10)
    store.add(make_record(transaction_id="a", decision=Decision.APPROVE, risk_score=0))
    store.add(make_record(transaction_id="b", decision=Decision.CHALLENGE, risk_score=40,
                          triggered_rules=("new_device",)))
    store.add(make_record(transaction_id="c", decision=Decision.BLOCK, risk_score=80,
                          amount=500.0, triggered_rules=("new_device", "velocity_burst")))

    payload = store.statistics()
    assert payload["total_transactions"] == 3
    assert payload["approved_transactions"] == 1
    assert payload["suspicious_transactions"] == 1
    assert payload["blocked_transactions"] == 1
    assert payload["average_risk_score"] == pytest.approx(40.0)
    assert payload["fraud_rate"] == pytest.approx(2 / 3, abs=0.001)
    assert payload["blocked_amount"] == pytest.approx(500.0)
    assert payload["triggered_rules"]["new_device"] == 2
