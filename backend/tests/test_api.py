"""Тесты HTTP-слоя (ТЗ §2.1, §8.2, §12, §15).

Проверяется не только «эндпоинт отвечает 200», но и свойства контракта:
пересчёт результата при изменении входа, влияние профиля клиента,
режим «что если», понятные ошибки и поведение без модели.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.config.settings import Settings
from app.features.definitions import FEATURE_NAMES
from app.main import create_app

BASE_TIME = datetime(2026, 9, 1, 14, 30, 0)


def transaction_body(**overrides) -> dict:
    """Обычная транзакция знакомого клиента с явно заданным контекстом.

    Контекст передаётся явно, поэтому ответ не зависит от накопленной
    истории и тесты не влияют друг на друга через профиль.
    """
    body = {
        "user_id": "user_test",
        "amount": 100.0,
        "timestamp": BASE_TIME.isoformat(),
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
        "user_avg_amount": 100.0,
        "user_amount_std": 30.0,
        "user_home_country": "KZ",
        "user_typical_frequency": 3.0,
        "known_device_ids": ["dev_known_1", "dev_known_2"],
        "previous_ip_address": "85.132.10.40",
        "previous_timestamp": (BASE_TIME - timedelta(hours=5)).isoformat(),
        "previous_latitude": 51.15,
        "previous_longitude": 71.40,
        "txn_count_last_hour": 1,
        "merchant_category": "grocery",
    }
    body.update(overrides)
    return body


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    """Приложение поднимается один раз: загрузка модели небыстрая.

    Архив разметки уводится во временный каталог. С настройками по
    умолчанию прогон тестов дописывал бы метки в рабочий
    `backend/data/feedback/labels.jsonl` — то есть в настоящую разметку
    разработчика, которую ничем не восстановить.
    """
    settings = Settings(
        feedback_path=str(tmp_path_factory.mktemp("feedback") / "labels.jsonl")
    )
    with TestClient(create_app(settings)) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def clean_state(client):
    """Каждый тест начинает с пустой историей, профилями и разметкой.

    Повторы тоже забываются. Без этого тесты протекали друг в друга
    через идемпотентность: два теста подряд занимают номера txn_0..txn_2,
    и второй получал их повтором — в очищенную историю они уже не
    попадали, хотя на живой системе это было бы верным поведением.
    """
    state = client.app.state.shin
    state.transactions.clear()
    state.profiles.clear()
    state.feedback.clear()
    if state.idempotency is not None:
        state.idempotency.clear()
    yield


# ------------------------------------------------------------- /health


def test_health_reports_ready_system(client) -> None:
    """DoD: /health возвращает статус и факт загрузки модели."""
    payload = client.get("/health").json()

    assert payload["status"] == "ok"
    assert payload["model_loaded"] is True
    assert payload["explainer_method"] in ("shap", "lightgbm_native", "ablation")
    assert payload["uptime_seconds"] >= 0


def test_health_counts_processed_transactions(client) -> None:
    client.post("/predict", json=transaction_body())
    client.post("/predict", json=transaction_body())
    assert client.get("/health").json()["transactions_processed"] == 2


def test_model_endpoint_exposes_metrics(client) -> None:
    payload = client.get("/model").json()
    assert payload["loaded"] is True
    # Число берётся из реестра, а не вписывается: прибитое гвоздём,
    # оно падает при каждом новом признаке и ничего не проверяет,
    # кроме того, что кто-то не забыл поправить тест.
    assert payload["feature_count"] == len(FEATURE_NAMES)
    assert 0.0 < payload["roc_auc"] <= 1.0


def test_health_degrades_without_model(tmp_path) -> None:
    """Без артефакта приложение обязано подняться и честно об этом сказать."""
    settings = Settings(model_path=str(tmp_path / "missing.joblib"))

    with TestClient(create_app(settings)) as degraded:
        payload = degraded.get("/health").json()
        assert payload["status"] == "degraded"
        assert payload["model_loaded"] is False

        response = degraded.post("/predict", json=transaction_body())
        assert response.status_code == 503
        assert response.json()["error_code"] == "model_not_loaded"
        assert "train_model.py" in response.json()["message"]


# ------------------------------------------------------------ /predict


def test_predict_returns_full_chain(client) -> None:
    """DoD: /predict отрабатывает всю цепочку."""
    payload = client.post("/predict", json=transaction_body()).json()

    for key in (
        "transaction_id", "risk_score", "model_score", "probability",
        "decision", "risk_level", "triggered_rules", "explanation",
        "thresholds", "features", "processing_ms",
    ):
        assert key in payload, f"в ответе нет поля {key}"

    assert 0 <= payload["risk_score"] <= 100
    assert len(payload["features"]) == len(FEATURE_NAMES)
    assert 3 <= len(payload["explanation"]["factors"]) <= 5


def test_normal_transaction_is_approved(client) -> None:
    payload = client.post("/predict", json=transaction_body()).json()
    assert payload["decision"] == "APPROVE"
    assert payload["risk_score"] <= payload["thresholds"]["approve_max"]


def test_risk_score_recomputed_on_changed_input(client) -> None:
    """ТЗ §15: результат обязан пересчитываться, а не браться из заглушки."""
    normal = client.post("/predict", json=transaction_body()).json()
    large = client.post("/predict", json=transaction_body(amount=5000.0)).json()
    anomalous = client.post(
        "/predict",
        json=transaction_body(
            amount=5000.0,
            country="NG",
            latitude=6.52,
            longitude=3.37,
            device_id="dev_attacker",
            ip_address="203.0.113.7",
            transaction_frequency=40,
            txn_count_last_hour=15,
        ),
    ).json()

    assert normal["risk_score"] < large["risk_score"] < anomalous["risk_score"]
    assert anomalous["decision"] == "BLOCK"


def test_policy_rules_are_reported(client) -> None:
    """Если оценку подняло правило, ответ обязан это показать."""
    payload = client.post(
        "/predict",
        json=transaction_body(device_id="dev_brand_new", ip_address="203.0.113.7"),
    ).json()

    assert payload["raised_by_rules"] is True
    assert payload["risk_score"] > payload["model_score"]
    assert any(rule["key"] == "new_device" for rule in payload["triggered_rules"])
    assert payload["explanation"]["policy_reasons"]


def test_transaction_id_is_generated_when_absent(client) -> None:
    body = transaction_body()
    payload = client.post("/predict", json=body).json()
    assert payload["transaction_id"].startswith("txn_")


def test_explicit_context_makes_result_reproducible(client) -> None:
    """Явный контекст защищает ручное тестирование от накопленной истории."""
    body = transaction_body(device_id="dev_known_1")
    first = client.post("/predict", json=body).json()
    second = client.post("/predict", json=body).json()

    assert first["risk_score"] == second["risk_score"]
    assert first["features"] == second["features"]


def test_profile_learns_device_when_context_omitted(client) -> None:
    """Без явного контекста система опирается на профиль и учится."""
    body = transaction_body(user_id="user_learning")
    body.pop("known_device_ids")
    body["device_id"] = "dev_first_seen"

    first = client.post("/predict", json=body).json()
    second = client.post("/predict", json=body).json()

    # Первая транзакция клиента — истории нет, устройство не считается новым.
    assert first["features"]["is_new_device"] == 0.0
    # После первой операции устройство стало известным и остаётся таким.
    assert second["features"]["is_new_device"] == 0.0
    assert second["features"]["known_device_count"] == 1.0


def test_new_device_detected_against_learned_profile(client) -> None:
    body = transaction_body(user_id="user_history")
    body.pop("known_device_ids")

    client.post("/predict", json={**body, "device_id": "dev_a"})
    payload = client.post("/predict", json={**body, "device_id": "dev_b"}).json()

    assert payload["features"]["is_new_device"] == 1.0


def test_persist_false_leaves_state_untouched(client) -> None:
    """Режим «что если»: ответ считается, состояние не меняется."""
    client.post("/predict", json=transaction_body())
    before = client.get("/stats").json()["total_transactions"]

    payload = client.post("/predict", json=transaction_body(persist=False)).json()
    after = client.get("/stats").json()["total_transactions"]

    assert payload["risk_score"] >= 0
    assert before == after == 1


# ------------------------------------------------------- валидация ввода


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("amount", -10.0),
        ("amount", 0),
        ("latitude", 120.0),
        ("longitude", -200.0),
        ("country", "KAZ"),
        ("ip_address", "не-ip"),
        ("transaction_frequency", -1),
        ("account_age_days", -5),
    ],
)
def test_invalid_field_is_rejected(client, field: str, value) -> None:
    response = client.post("/predict", json=transaction_body(**{field: value}))
    assert response.status_code == 422


def test_validation_error_is_readable(client) -> None:
    """Ошибка должна называть поле и причину, а не отдавать сырой pydantic."""
    response = client.post("/predict", json=transaction_body(amount=-1))
    payload = response.json()

    assert payload["error_code"] == "validation_error"
    fields = [error["field"] for error in payload["details"]["errors"]]
    assert "amount" in fields


def test_country_code_is_normalized(client) -> None:
    payload = client.post("/predict", json=transaction_body(country="kz")).json()
    assert payload["features"]["is_unusual_country"] == 0.0


def test_missing_required_field_is_rejected(client) -> None:
    body = transaction_body()
    del body["user_id"]
    assert client.post("/predict", json=body).status_code == 422


def test_previous_timestamp_after_timestamp_is_rejected(client) -> None:
    """Противоречивая хронология не должна приниматься молча.

    Раньше такой запрос давал HTTP 200: отрицательный интервал зажимался
    в ноль, и ответ показывал скорость перемещения, взявшуюся из ниоткуда.
    """
    body = transaction_body(previous_timestamp=(BASE_TIME + timedelta(hours=3)).isoformat())
    response = client.post("/predict", json=body)

    assert response.status_code == 422
    fields = [error["field"] for error in response.json()["details"]["errors"]]
    assert "previous_timestamp" in fields


def test_future_previous_timestamp_is_rejected_without_explicit_timestamp(client) -> None:
    """Пустой `timestamp` означает «сейчас» — «предыдущая» в будущем невозможна."""
    body = transaction_body(previous_timestamp=datetime(2099, 1, 1).isoformat())
    del body["timestamp"]

    assert client.post("/predict", json=body).status_code == 422


def test_simultaneous_transactions_are_allowed(client) -> None:
    """Нулевой интервал — законный случай, отвергать его нельзя."""
    body = transaction_body(previous_timestamp=BASE_TIME.isoformat())

    assert client.post("/predict", json=body).status_code == 200


def test_chronology_is_compared_in_utc(client) -> None:
    """Сравнение идёт после приведения к UTC, а не по номиналу.

    15:00+06:00 — это 09:00 UTC, то есть раньше наивных 14:30. Проверка,
    сравнивающая исходные значения, отвергла бы законный запрос.
    """
    body = transaction_body(previous_timestamp="2026-09-01T15:00:00+06:00")

    assert client.post("/predict", json=body).status_code == 200


def test_zero_counters_are_normalised_not_rejected(client) -> None:
    """Ноль в счётчиках — не ошибка ввода, а другое прочтение поля.

    Отвергать такой запрос было бы грубо: клиент вправе считать операции
    до текущей. Поэтому значение приводится к единице, а не к 422.
    """
    payload = client.post(
        "/predict", json=transaction_body(transaction_frequency=0, txn_count_last_hour=0)
    ).json()

    assert payload["features"]["transaction_frequency"] == 1.0
    assert payload["features"]["txn_count_last_hour"] == 1.0


def test_framework_errors_follow_the_same_contract(client) -> None:
    """404 и 405 обязаны отвечать так же, как собственные ошибки.

    Starlette отдаёт свою форму {"detail": ...}, а весь остальной API —
    {error_code, message, details}. Клиент читает message, не находил его
    и показывал голое «HTTP 404» вместо объяснения.
    """
    for response in (client.get("/такого-адреса-нет"), client.get("/predict")):
        payload = response.json()

        assert response.status_code in (404, 405)
        assert set(payload) == {"error_code", "message", "details"}
        assert payload["message"] and not payload["message"].startswith("HTTP")


def test_method_not_allowed_keeps_allow_header(client) -> None:
    """Заголовок Allow — часть ответа 405, и обработчик не должен его терять."""
    response = client.get("/predict")

    assert response.status_code == 405
    assert "allow" in {name.lower() for name in response.headers}


def test_malformed_body_is_explained(client) -> None:
    """Нечитаемое тело объясняется словами, а не кодом."""
    response = client.post(
        "/predict", content="{это не json", headers={"Content-Type": "application/json"}
    )

    assert response.status_code in (400, 422)
    payload = response.json()
    assert "error_code" in payload
    assert payload["message"]


# --------------------------------------------------------------- /stats


def test_stats_are_empty_before_any_traffic(client) -> None:
    payload = client.get("/stats").json()
    assert payload["total_transactions"] == 0
    assert payload["average_risk_score"] == 0.0
    assert payload["fraud_rate"] == 0.0


def test_stats_reflect_processed_traffic(client) -> None:
    """DoD: /stats считает реальную статистику, а не берёт её из датасета."""
    client.post("/predict", json=transaction_body())
    client.post("/predict", json=transaction_body(
        amount=5000.0, country="NG", latitude=6.52, longitude=3.37,
        device_id="dev_attacker", ip_address="203.0.113.7",
        transaction_frequency=40, txn_count_last_hour=15,
    ))

    payload = client.get("/stats").json()

    assert payload["total_transactions"] == 2
    assert payload["approved_transactions"] + payload["suspicious_transactions"] \
        + payload["blocked_transactions"] == 2
    assert payload["blocked_transactions"] >= 1
    assert payload["total_amount"] == pytest.approx(5100.0)
    assert 0.0 < payload["fraud_rate"] <= 1.0
    assert payload["top_countries"]
    assert payload["triggered_rules"]


# -------------------------------------------------------- /transactions


def test_transactions_are_listed_newest_first(client) -> None:
    for index in range(3):
        client.post("/predict", json=transaction_body(transaction_id=f"txn_{index}"))

    items = client.get("/transactions").json()["items"]
    assert [item["transaction_id"] for item in items] == ["txn_2", "txn_1", "txn_0"]


def test_transactions_filter_by_decision(client) -> None:
    client.post("/predict", json=transaction_body())
    client.post("/predict", json=transaction_body(
        amount=5000.0, country="NG", latitude=6.52, longitude=3.37,
        device_id="dev_attacker", ip_address="203.0.113.7",
        transaction_frequency=40, txn_count_last_hour=15,
    ))

    blocked = client.get("/transactions", params={"decision": "BLOCK"}).json()
    assert blocked["total"] >= 1
    assert all(item["decision"] == "BLOCK" for item in blocked["items"])

    approved = client.get("/transactions", params={"decision": "APPROVE"}).json()
    assert all(item["decision"] == "APPROVE" for item in approved["items"])


def test_transactions_filter_flagged_covers_both_held_decisions(client) -> None:
    """«Только задержанные» — это CHALLENGE и BLOCK вместе.

    Фильтр по одному решению для ленты аналитика не годится: его вопрос
    «с чем система что-то сделала», а не «что именно она сделала».
    Отбирать же на клиенте нельзя — тогда «только задержанные» показывало
    бы задержанные из последних двадцати пяти, а не последние двадцать
    пять задержанных.
    """
    client.post("/predict", json=transaction_body())
    client.post("/predict", json=transaction_body(
        amount=5000.0, country="NG", latitude=6.52, longitude=3.37,
        device_id="dev_attacker", ip_address="203.0.113.7",
        transaction_frequency=40, txn_count_last_hour=15,
    ))

    flagged = client.get("/transactions", params={"flagged": True}).json()
    approved = client.get("/transactions", params={"flagged": False}).json()
    everything = client.get("/transactions").json()

    assert flagged["total"] >= 1, "ни одной задержанной — проверять нечего"
    assert all(item["decision"] != "APPROVE" for item in flagged["items"])
    assert all(item["decision"] == "APPROVE" for item in approved["items"])
    # Две половины обязаны складываться в целое: иначе фильтр теряет строки.
    assert flagged["total"] + approved["total"] == everything["total"]


def test_flagged_filter_keeps_both_kinds_at_once(client) -> None:
    """Оба вида задержанных обязаны попасть в один ответ.

    Проверка против фильтра, который ловит только одно из двух решений:
    с `decision=BLOCK` он выглядел бы работающим, а половину работы
    аналитика — все операции на доп. проверку — тихо прятал.
    """
    # Незнакомое устройство в незнакомой сети — доп. проверка.
    challenge = client.post("/predict", json=transaction_body(
        device_id="dev_new_one", ip_address="203.0.113.9",
    )).json()
    # Крупная сумма с незнакомого устройства — блокировка.
    block = client.post("/predict", json=transaction_body(
        amount=20000.0, device_id="dev_new_two", ip_address="198.51.100.9",
    )).json()

    # Решения закреплены явно: если модель после переобучения начнёт
    # судить иначе, тест обязан сказать об этом прямо, а не молча
    # проверять одно решение вместо двух.
    assert challenge["decision"] == "CHALLENGE"
    assert block["decision"] == "BLOCK"

    decisions = {
        item["decision"]
        for item in client.get("/transactions", params={"flagged": True}).json()["items"]
    }

    assert "CHALLENGE" in decisions, "доп. проверки потеряны фильтром"
    assert "BLOCK" in decisions, "блокировки потеряны фильтром"
    assert "APPROVE" not in decisions


def test_transactions_filter_by_country_and_score(client) -> None:
    client.post("/predict", json=transaction_body())
    client.post("/predict", json=transaction_body(
        country="NG", latitude=6.52, longitude=3.37, ip_address="197.210.44.12",
    ))

    by_country = client.get("/transactions", params={"country": "NG"}).json()
    assert by_country["total"] == 1
    assert by_country["items"][0]["country"] == "NG"

    high = client.get("/transactions", params={"min_risk_score": 31}).json()
    assert all(item["risk_score"] >= 31 for item in high["items"])


def test_transactions_pagination(client) -> None:
    for index in range(5):
        client.post("/predict", json=transaction_body(transaction_id=f"txn_{index}"))

    page = client.get("/transactions", params={"limit": 2, "offset": 1}).json()
    assert page["total"] == 5
    assert page["returned"] == 2
    assert [item["transaction_id"] for item in page["items"]] == ["txn_3", "txn_2"]


# ------------------------------------------------------- инфраструктура


def test_cors_allows_frontend_origin(client) -> None:
    """ТЗ §12: CORS для frontend."""
    response = client.options(
        "/predict",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert response.status_code in (200, 204)
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


# -------------------------------------------- разметка аналитика


def analyze(client, **overrides) -> dict:
    """Провести операцию через систему, чтобы её было что размечать."""
    return client.post("/predict", json=transaction_body(**overrides)).json()


def test_feedback_turns_a_verdict_into_a_label(client) -> None:
    """Аналитик отвечает «система права?», а система выводит настоящую метку."""
    predicted = analyze(client, transaction_id="txn_feedback_1")

    response = client.post(
        f"/transactions/{predicted['transaction_id']}/feedback",
        json={"verdict": "INCORRECT", "analyst": "ops", "comment": "клиент подтвердил покупку"},
    )
    assert response.status_code == 200
    record = response.json()["record"]

    assert record["verdict"] == "INCORRECT"
    assert record["decision"] == predicted["decision"]
    # Решение системы копируется в метку: транзакцию вытеснит из буфера,
    # а размеченная строка должна остаться пригодной для дообучения.
    assert record["risk_score"] == predicted["risk_score"]
    assert record["analyst"] == "ops"


def test_feedback_returns_the_recalculated_summary(client) -> None:
    """Сводка приходит тем же ответом — лишний круг по сети ни к чему."""
    analyze(client, transaction_id="txn_feedback_2")

    summary = client.post(
        "/transactions/txn_feedback_2/feedback", json={"verdict": "CORRECT"}
    ).json()["summary"]

    assert summary["labeled_total"] == 1
    assert summary["correct"] == 1
    assert summary["correct_share"] == 1.0


def test_relabeling_replaces_and_does_not_double_count(client) -> None:
    analyze(client, transaction_id="txn_feedback_3")

    client.post("/transactions/txn_feedback_3/feedback", json={"verdict": "CORRECT"})
    second = client.post(
        "/transactions/txn_feedback_3/feedback", json={"verdict": "INCORRECT"}
    ).json()

    assert second["summary"]["labeled_total"] == 1
    assert second["summary"]["incorrect"] == 1


def test_feedback_on_unknown_transaction_explains_both_causes(client) -> None:
    """Опечатка и `persist=false` выглядят одинаково — говорим обе причины."""
    response = client.post(
        "/transactions/txn_never-existed/feedback", json={"verdict": "CORRECT"}
    )

    assert response.status_code == 404
    payload = response.json()
    assert payload["error_code"] == "transaction_not_found"
    assert "persist=false" in payload["message"]


def test_unsaved_transaction_cannot_be_labeled(client) -> None:
    """Режим «что если» историю не меняет, значит и размечать нечего."""
    client.post("/predict", json=transaction_body(transaction_id="txn_ghost", persist=False))

    response = client.post("/transactions/txn_ghost/feedback", json={"verdict": "CORRECT"})
    assert response.status_code == 404


def test_empty_transaction_id_is_rejected_at_the_border(client) -> None:
    """Пустой идентификатор попадал в историю, а разметить его было нечем:
    адрес /transactions//feedback никуда не ведёт."""
    response = client.post("/predict", json=transaction_body(transaction_id=""))

    assert response.status_code == 422
    assert any("transaction_id" in item["field"] for item in response.json()["details"]["errors"])


def test_feedback_rejects_an_unknown_verdict(client) -> None:
    analyze(client, transaction_id="txn_feedback_4")

    response = client.post(
        "/transactions/txn_feedback_4/feedback", json={"verdict": "MAYBE"}
    )
    assert response.status_code == 422
    assert response.json()["error_code"] == "validation_error"


def test_summary_is_empty_before_any_labeling(client) -> None:
    payload = client.get("/feedback/summary").json()

    assert payload["labeled_total"] == 0
    # Не ноль: «точность 0 %» и «ещё не измерена» — разные утверждения.
    assert payload["precision"] is None
    assert payload["correct_share"] is None


def test_accumulated_labels_are_retrievable(client) -> None:
    """На эфемерном диске это единственный способ забрать разметку наружу."""
    for index in (1, 2):
        analyze(client, transaction_id=f"txn_list_{index}")
        client.post(f"/transactions/txn_list_{index}/feedback", json={"verdict": "CORRECT"})

    payload = client.get("/feedback").json()

    assert payload["total"] == 2
    assert {item["transaction_id"] for item in payload["items"]} == {
        "txn_list_1",
        "txn_list_2",
    }


def test_transactions_table_shows_what_is_already_labeled(client) -> None:
    """Без пометки аналитик разбирал бы одно и то же дважды."""
    analyze(client, transaction_id="txn_marked")
    analyze(client, transaction_id="txn_untouched")
    client.post("/transactions/txn_marked/feedback", json={"verdict": "CORRECT"})

    rows = {item["transaction_id"]: item for item in client.get("/transactions").json()["items"]}

    assert rows["txn_marked"]["verdict"] == "CORRECT"
    assert rows["txn_marked"]["actual_fraud"] is not None
    assert rows["txn_untouched"]["verdict"] is None


def test_labels_are_written_to_disk(client) -> None:
    """Ручную работу человека нельзя терять при перезапуске."""
    analyze(client, transaction_id="txn_persisted")
    client.post("/transactions/txn_persisted/feedback", json={"verdict": "CORRECT"})

    archive = client.app.state.shin.feedback.path
    assert archive.exists()
    assert "txn_persisted" in archive.read_text(encoding="utf-8")


def test_openapi_schema_is_available(client) -> None:
    """ТЗ §2.1: Swagger обязателен для ручного тестирования."""
    spec = client.get("/openapi.json").json()

    assert "/predict" in spec["paths"]
    assert "/health" in spec["paths"]
    assert "/stats" in spec["paths"]
    assert client.get("/docs").status_code == 200


def test_predict_schema_documents_example(client) -> None:
    spec = client.get("/openapi.json").json()
    schema = spec["components"]["schemas"]["TransactionRequest"]
    assert "example" in schema or "examples" in schema


def test_unknown_route_returns_404(client) -> None:
    assert client.get("/no-such-endpoint").status_code == 404
