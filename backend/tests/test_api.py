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
def client():
    """Приложение поднимается один раз: загрузка модели небыстрая."""
    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def clean_state(client):
    """Каждый тест начинает с пустой историей и пустыми профилями."""
    state = client.app.state.shin
    state.transactions.clear()
    state.profiles.clear()
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
    assert payload["feature_count"] == 27
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
    assert len(payload["features"]) == 27
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
