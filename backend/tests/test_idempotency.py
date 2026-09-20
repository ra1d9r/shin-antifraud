"""Тесты идемпотентности `POST /predict`.

Повтор запроса — обычное дело: клиент не дождался ответа, прокси повторил
за него, пользователь нажал дважды. Проверяется не только «ответ тот же»,
но и то, ради чего всё затевалось: повтор **не оставляет следов** —
ни в истории, ни в профиле, ни в наблюдениях.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config.settings import Settings
from app.main import create_app
from app.store.idempotency import IdempotencyConflictError, IdempotencyStore, fingerprint

BASE_TIME = "2026-09-01T14:30:00"


def transaction(**overrides) -> dict:
    body = {
        "transaction_id": "txn_idem",
        "user_id": "user_idem",
        "amount": 100.0,
        "timestamp": BASE_TIME,
        "merchant": "Magnum",
        "country": "KZ",
        "device_id": "dev_known_1",
        "ip_address": "85.132.10.55",
        "latitude": 51.16,
        "longitude": 71.44,
        "transaction_frequency": 3,
        "previous_transaction_amount": 95.0,
        "previous_transaction_country": "KZ",
        "account_age_days": 800,
    }
    body.update(overrides)
    return body


@pytest.fixture(scope="module")
def client():
    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def clean(client):
    state = client.app.state.shin
    state.transactions.clear()
    state.profiles.clear()
    if state.idempotency:
        state.idempotency.clear()
    yield


# ------------------------------------------------------------- отпечаток


def test_field_order_does_not_change_the_fingerprint() -> None:
    """Порядок ключей в JSON произволен, и без сортировки один и тот же
    запрос давал бы разные отпечатки в зависимости от клиента."""
    assert fingerprint({"a": 1, "b": 2}) == fingerprint({"b": 2, "a": 1})


def test_different_data_gives_a_different_fingerprint() -> None:
    assert fingerprint({"amount": 100}) != fingerprint({"amount": 101})


# ------------------------------------------------------- поведение повтора


def test_repeat_returns_the_same_answer(client) -> None:
    first = client.post("/predict", json=transaction())
    second = client.post("/predict", json=transaction())

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()


def test_repeat_is_marked_with_a_header(client) -> None:
    """Клиенты, которые умеют идемпотентность, ищут именно этот заголовок."""
    first = client.post("/predict", json=transaction())
    second = client.post("/predict", json=transaction())

    assert "Idempotent-Replay" not in first.headers
    assert second.headers["Idempotent-Replay"] == "true"


def test_repeat_does_not_count_twice(client) -> None:
    for _ in range(4):
        client.post("/predict", json=transaction())

    assert client.get("/transactions").json()["total"] == 1
    assert client.get("/stats").json()["total_transactions"] == 1


def test_repeat_does_not_move_the_client_profile(client) -> None:
    """Главное, ради чего всё затевалось.

    Профиль, обновлённый первым вызовом, менял ответ на второй:
    устройство, которое было новым, новым быть переставало. Клиент
    переспрашивал из-за таймаута и получал другой вердикт по той же
    операции.
    """
    body = transaction(device_id="dev_never_seen", user_id="user_fresh")

    client.post("/predict", json=body)
    profile_after_first = client.app.state.shin.profiles.get("user_fresh").known_devices.copy()
    client.post("/predict", json=body)

    assert client.app.state.shin.profiles.get("user_fresh").known_devices == profile_after_first


def test_repeat_does_not_reach_the_observers(client) -> None:
    state = client.app.state.shin
    if state.drift is None or state.shadow is None:
        pytest.skip("наблюдения не собраны")
    state.drift.reset()
    state.shadow.reset()

    client.post("/predict", json=transaction())
    client.post("/predict", json=transaction())

    assert client.get("/monitoring/drift").json()["observed_rows"] == 1
    assert client.get("/monitoring/shadow").json()["observed"] == 1


def test_same_number_with_other_data_is_refused(client) -> None:
    """Это не повтор, а вторая операция под чужим номером.

    Вернуть закэшированное было бы хуже молчаливой ошибки: клиент
    получил бы решение по чужим данным и не узнал бы об этом.
    """
    client.post("/predict", json=transaction())
    conflict = client.post("/predict", json=transaction(amount=99_999.0))

    assert conflict.status_code == 409
    payload = conflict.json()
    assert payload["error_code"] == "idempotency_conflict"
    assert "transaction_id" in payload["message"]
    assert payload["details"]["transaction_id"] == "txn_idem"


def test_conflict_does_not_process_the_transaction(client) -> None:
    client.post("/predict", json=transaction())
    client.post("/predict", json=transaction(amount=99_999.0))

    assert client.get("/transactions").json()["total"] == 1


def test_different_numbers_are_processed_separately(client) -> None:
    client.post("/predict", json=transaction(transaction_id="txn_a"))
    client.post("/predict", json=transaction(transaction_id="txn_b"))

    assert client.get("/transactions").json()["total"] == 2


def test_what_if_mode_is_never_cached(client) -> None:
    """Режим «что если» существует ровно для того, чтобы гонять один
    и тот же ввод сколько угодно раз."""
    first = client.post("/predict", json=transaction(persist=False))
    second = client.post("/predict", json=transaction(persist=False, amount=250.0))

    assert first.status_code == second.status_code == 200
    assert "Idempotent-Replay" not in second.headers
    # Тот же номер с другими данными в режиме «что если» — не конфликт.
    assert second.json()["risk_score"] >= 0


def test_what_if_does_not_block_the_real_one(client) -> None:
    """Прикидка не должна занимать номер настоящей операции."""
    client.post("/predict", json=transaction(persist=False))
    real = client.post("/predict", json=transaction(amount=777.0))

    assert real.status_code == 200
    assert client.get("/transactions").json()["total"] == 1


# ------------------------------------------------------------ хранилище


def test_oldest_entries_are_evicted() -> None:
    store = IdempotencyStore(capacity=2)
    store.remember("a", "d1", "ответ a")
    store.remember("b", "d2", "ответ b")
    store.remember("c", "d3", "ответ c")

    assert store.size() == 2
    assert store.lookup("a", "d1") is None
    assert store.lookup("c", "d3") == "ответ c"


def test_a_repeated_key_is_pushed_away_from_eviction() -> None:
    """То, что переспрашивают, нужнее того, что забыли."""
    store = IdempotencyStore(capacity=2)
    store.remember("a", "d1", "ответ a")
    store.remember("b", "d2", "ответ b")
    store.lookup("a", "d1")  # обращение к 'a' отодвигает его от края
    store.remember("c", "d3", "ответ c")

    assert store.lookup("a", "d1") == "ответ a"
    assert store.lookup("b", "d2") is None


def test_store_counts_replays_and_conflicts() -> None:
    store = IdempotencyStore(capacity=10)
    store.remember("a", "d1", "ответ")
    store.lookup("a", "d1")
    store.lookup("a", "d1")
    with pytest.raises(IdempotencyConflictError):
        store.lookup("a", "другой")

    assert (store.replays, store.conflicts) == (2, 1)


def test_capacity_must_be_positive() -> None:
    with pytest.raises(ValueError, match="положительным"):
        IdempotencyStore(capacity=0)


# ------------------------------------------------------------ выключение


def test_disabled_idempotency_processes_every_request(tmp_path) -> None:
    """Выключатель обязан возвращать прежнее поведение целиком."""
    settings = Settings(idempotency_enabled=False)

    with TestClient(create_app(settings)) as plain:
        plain.post("/predict", json=transaction())
        second = plain.post("/predict", json=transaction())

        assert "Idempotent-Replay" not in second.headers
        assert plain.get("/transactions").json()["total"] == 2
        # И конфликта тоже нет: проверять нечем.
        assert plain.post("/predict", json=transaction(amount=5.0)).status_code == 200
