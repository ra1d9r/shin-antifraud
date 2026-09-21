"""Тесты пакетной обработки (брифинг §4.1, §5.B).

Два режима — партия и поток — проверяются по-разному, потому что нужны
для разного. От партии требуется вердикт по каждой операции и та же
защита от повторов, что у одиночного `/predict`. От потока — чтобы
система действительно поработала: ради этого он и существует.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.routes.batch import POOL_ROWS, _to_request
from app.main import create_app
from app.schemas.batch import MAX_BATCH, MAX_STREAM

BASE_TIME = "2026-09-01T14:30:00"


def transaction(**overrides) -> dict:
    body = {
        "user_id": "user_batch",
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


# --------------------------------------------------------------- партия


def test_batch_answers_every_transaction_in_order(client) -> None:
    """Порядок ответа совпадает с порядком запроса.

    Иначе сопоставить вердикт с операцией можно было бы только по номеру,
    а номер необязателен — система присваивает его сама.
    """
    sent = ["batch_first", "batch_second", "batch_third", "batch_fourth"]
    body = {
        "transactions": [
            transaction(transaction_id=sent[0], amount=100.0),
            transaction(transaction_id=sent[1], amount=90_000.0),
            transaction(transaction_id=sent[2], amount=250.0),
            transaction(transaction_id=sent[3], amount=500.0),
        ]
    }

    payload = client.post("/predict/batch", json=body).json()

    assert payload["summary"]["processed"] == 4
    # Сверяются номера, а не баллы: перестановка списка баллами не ловится,
    # если одинаковые значения окажутся симметрично.
    assert [item["transaction_id"] for item in payload["results"]] == sent

    # Средняя по партии выведена из тех же вердиктов, а не посчитана заново.
    scores = [item["risk_score"] for item in payload["results"]]
    assert payload["summary"]["average_risk_score"] == pytest.approx(
        sum(scores) / 4, abs=0.01
    )


def test_batch_summary_counts_agree_with_results(client) -> None:
    body = {
        "transactions": [
            transaction(amount=100.0),
            transaction(amount=90_000.0, country="NG", device_id="dev_new"),
        ]
    }

    payload = client.post("/predict/batch", json=body).json()
    results = payload["results"]
    summary = payload["summary"]

    for decision, count in summary["decisions"].items():
        assert count == sum(1 for item in results if item["decision"] == decision)
    assert sum(summary["decisions"].values()) == len(results)
    assert summary["raised_by_rules"] == sum(1 for item in results if item["raised_by_rules"])


def test_repeating_a_batch_changes_nothing(client) -> None:
    """Главное свойство: повтор партии не удваивает последствий.

    Без него клиент, у которого оборвалась сеть на середине ответа, при
    повторе получил бы вторую копию каждой операции в истории и сдвинутые
    профили — то есть ровно тот вред, ради которого заводилась
    идемпотентность одиночного `/predict`.
    """
    body = {
        "transactions": [
            transaction(transaction_id="batch_1"),
            transaction(transaction_id="batch_2", amount=500.0),
        ]
    }

    first = client.post("/predict/batch", json=body).json()
    after_first = client.get("/transactions").json()["total"]

    second = client.post("/predict/batch", json=body).json()
    after_second = client.get("/transactions").json()["total"]

    assert first["replayed"] == 0
    assert second["replayed"] == 2
    assert after_second == after_first, "повтор не должен добавлять операций в историю"
    assert [item["risk_score"] for item in second["results"]] == [
        item["risk_score"] for item in first["results"]
    ]


def test_same_number_with_other_data_is_a_conflict(client) -> None:
    """Партия наследует и обратную сторону идемпотентности."""
    client.post("/predict/batch", json={"transactions": [transaction(transaction_id="batch_x")]})

    response = client.post(
        "/predict/batch",
        json={"transactions": [transaction(transaction_id="batch_x", amount=777.0)]},
    )

    assert response.status_code == 409


def test_a_conflict_in_the_middle_leaves_no_trace(client) -> None:
    """Отказ по занятому номеру не оставляет половину партии записанной.

    Так было до проверки номеров: операции обрабатывались по очереди,
    конфликт возникал на третьей, и первые две уже лежали в истории
    и сдвинули профили. Клиент получал 409 и не знал, что именно прошло,
    а повторить партию не мог — тот же конфликт возникал снова.
    """
    client.post("/predict", json=transaction(transaction_id="occupied", amount=11.0))
    before = client.get("/transactions").json()["total"]

    response = client.post(
        "/predict/batch",
        json={
            "transactions": [
                transaction(transaction_id="fresh_1"),
                transaction(transaction_id="fresh_2"),
                transaction(transaction_id="occupied", amount=999.0),
                transaction(transaction_id="fresh_3"),
            ]
        },
    )

    assert response.status_code == 409
    assert client.get("/transactions").json()["total"] == before, (
        "ни одна операция партии не должна быть записана"
    )
    # Виновник назван: без этого клиенту пришлось бы искать его перебором.
    assert "occupied" in response.json()["details"]["transaction_ids"]


def test_the_same_number_twice_inside_one_batch_is_a_conflict(client) -> None:
    """Дубликат номера внутри партии ловится так же, как занятый снаружи.

    Первая из двух записала бы номер, вторая упала бы на конфликте —
    и снова с половиной партии в истории.
    """
    response = client.post(
        "/predict/batch",
        json={
            "transactions": [
                transaction(transaction_id="twin", amount=100.0),
                transaction(transaction_id="twin", amount=200.0),
            ]
        },
    )

    assert response.status_code == 409
    assert client.get("/transactions").json()["total"] == 0


def test_the_same_number_twice_with_the_same_body_is_allowed(client) -> None:
    """А вот дословный дубликат — это повтор, и он безопасен по построению."""
    body = transaction(transaction_id="echo")
    response = client.post("/predict/batch", json={"transactions": [body, body]})

    assert response.status_code == 200
    payload = response.json()
    assert payload["replayed"] == 1, "вторая копия обслужена повтором"
    assert client.get("/transactions").json()["total"] == 1


def test_batch_size_is_capped(client) -> None:
    """Ответ содержит полный разбор каждой операции, поэтому партия ограничена."""
    body = {"transactions": [transaction() for _ in range(MAX_BATCH + 1)]}

    assert client.post("/predict/batch", json=body).status_code == 422


def test_empty_batch_is_rejected(client) -> None:
    assert client.post("/predict/batch", json={"transactions": []}).status_code == 422


def test_broken_transaction_fails_the_whole_batch(client) -> None:
    """Частичный результат с дырками хуже отказа: по нему не понять,
    какие операции обработаны, а какие нет."""
    body = {"transactions": [transaction(), transaction(amount=-5.0)]}

    assert client.post("/predict/batch", json=body).status_code == 422
    assert client.get("/transactions").json()["total"] == 0


# ---------------------------------------------------------------- поток


def test_stream_processes_what_was_asked(client) -> None:
    summary = client.post("/predict/stream", json={"count": 25, "seed": 1}).json()

    assert summary["requested"] == 25
    assert summary["processed"] == 25
    assert summary["pool_rows"] <= POOL_ROWS
    assert sum(summary["decisions"].values()) == 25


def test_stream_quality_counters_add_up(client) -> None:
    """Разметка потока известна, и сводка обязана её не терять."""
    summary = client.post("/predict/stream", json={"count": 60, "seed": 3}).json()

    assert summary["fraud_stopped"] + summary["fraud_missed"] == summary["fraud_in_stream"]
    assert summary["fraud_in_stream"] <= summary["processed"]
    assert summary["false_positives"] <= summary["processed"] - summary["fraud_in_stream"]


def test_the_same_seed_gives_the_same_stream(client) -> None:
    """Воспроизводимость: иначе прогон нельзя обсудить и повторить."""
    first = client.post("/predict/stream", json={"count": 30, "seed": 99}).json()
    second = client.post("/predict/stream", json={"count": 30, "seed": 99}).json()

    assert first["seed"] == second["seed"] == 99
    assert first["fraud_in_stream"] == second["fraud_in_stream"]
    assert first["decisions"] == second["decisions"]


def test_stream_without_a_seed_picks_one_and_reports_it(client) -> None:
    """Зерно по умолчанию случайное, иначе два прогона подряд прислали бы
    те же `transaction_id` и выглядели бы в истории дубликатами."""
    summary = client.post("/predict/stream", json={"count": 10}).json()

    assert isinstance(summary["seed"], int)
    assert summary["processed"] == 10


def test_stream_feeds_the_monitors(client) -> None:
    """То, ради чего эндпоинт и появился.

    Наблюдение за дрейфом, тень и история операций на свежей системе
    пусты, и понять, работают ли панели, нельзя. Проверяется именно
    прирост: абсолютные значения зависят от того, что уже прогнали.
    """
    before_drift = client.get("/monitoring/drift").json()["observed_rows"]
    before_shadow = client.get("/monitoring/shadow").json()["observed"]

    client.post("/predict/stream", json={"count": 40, "seed": 5})

    assert client.get("/monitoring/drift").json()["observed_rows"] == before_drift + 40
    assert client.get("/monitoring/shadow").json()["observed"] == before_shadow + 40
    assert client.get("/transactions").json()["total"] == 40


def test_stream_length_is_capped(client) -> None:
    """Ограничение здесь про время: каждая операция идёт полной цепочкой."""
    assert client.post("/predict/stream", json={"count": MAX_STREAM + 1}).status_code == 422
    assert client.post("/predict/stream", json={"count": 0}).status_code == 422


# ------------------------------------------------- строка датасета -> запрос


def test_row_conversion_splits_the_device_list() -> None:
    """Генератор хранит устройства строкой через `|`, схема ждёт список.

    Без разбора список известных устройств оказался бы пустым, признак
    «новое устройство» срабатывал бы на каждой операции потока, и весь
    прогон уехал бы в CHALLENGE.
    """
    request = _to_request(
        {
            "user_id": "u1",
            "amount": 100.0,
            "timestamp": BASE_TIME,
            "merchant": "Magnum",
            "country": "KZ",
            "device_id": "dev_a",
            "ip_address": "85.132.10.55",
            "latitude": 51.16,
            "longitude": 71.44,
            "transaction_frequency": 3,
            "previous_transaction_amount": 95.0,
            "previous_transaction_country": "KZ",
            "account_age_days": 800,
            "known_device_ids": "dev_a|dev_b",
            "fraud_scenario": "none",
            "txn_count_last_24h": 4,
        }
    )

    assert request.known_device_ids == ["dev_a", "dev_b"]
    # Колонки, которых нет в схеме, отброшены, а не уронили разбор.
    assert not hasattr(request, "fraud_scenario")


def test_row_conversion_drops_missing_values() -> None:
    """Пропуск в кадре — это NaN, а схема ждёт либо значение, либо ничего."""
    import numpy as np

    request = _to_request(
        {
            "user_id": "u1",
            "amount": 100.0,
            "timestamp": BASE_TIME,
            "merchant": "Magnum",
            "country": "KZ",
            "device_id": "dev_a",
            "ip_address": "85.132.10.55",
            "latitude": 51.16,
            "longitude": 71.44,
            "transaction_frequency": 3,
            "previous_transaction_amount": 95.0,
            "previous_transaction_country": "KZ",
            "account_age_days": 800,
            "user_avg_amount": np.nan,
            "previous_ip_address": None,
        }
    )

    assert request.user_avg_amount is None
    assert request.previous_ip_address is None
