"""Тесты текстового отчёта по операции.

Отчёт уходит в тикет и в переписку с клиентской службой, то есть живёт
дольше и дальше, чем ответ API. Поэтому проверяется не «строка не пустая»,
а то, без чего им нельзя пользоваться: решение, его причина, чем оно
посчитано, — и то, что сам отчёт ничего не меняет.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.config.settings import Settings
from app.main import create_app
from app.reports.transaction import DECISION_MEANING, render_transaction_report
from app.schemas.enums import Decision

BASE_TIME = datetime(2026, 9, 1, 3, 14, 0)


def transaction(**overrides) -> dict:
    """Ночная операция на крупную сумму из чужой страны с нового устройства."""
    body = {
        "transaction_id": "txn_report",
        "user_id": "user_00042",
        "amount": 45_000.0,
        "timestamp": BASE_TIME.isoformat(),
        "merchant": "Crypto Exchange",
        "country": "NG",
        "device_id": "dev_unknown_99",
        "ip_address": "203.0.113.45",
        "latitude": 6.45,
        "longitude": 3.39,
        "transaction_frequency": 9,
        "previous_transaction_amount": 120.0,
        "previous_transaction_country": "KZ",
        "account_age_days": 12,
        "user_avg_amount": 150.0,
        "user_home_country": "KZ",
        "known_device_ids": ["dev_known_1"],
        "previous_ip_address": "85.132.10.40",
        "previous_timestamp": "2026-09-01T02:30:00",
        "previous_latitude": 51.16,
        "previous_longitude": 71.44,
        "txn_count_last_hour": 7,
    }
    body.update(overrides)
    return body


def calm(**overrides) -> dict:
    """Обычная покупка знакомого клиента: политики молчат."""
    return transaction(
        transaction_id="txn_calm",
        amount=100.0,
        timestamp="2026-09-01T14:30:00",
        merchant="Magnum",
        country="KZ",
        device_id="dev_known_1",
        ip_address="85.132.10.55",
        latitude=51.16,
        longitude=71.44,
        transaction_frequency=3,
        previous_transaction_amount=95.0,
        account_age_days=800,
        user_avg_amount=100.0,
        txn_count_last_hour=1,
        previous_ip_address="85.132.10.55",
        previous_timestamp="2026-09-01T09:30:00",
        previous_latitude=51.16,
        previous_longitude=71.44,
        **overrides,
    )


@pytest.fixture(scope="module")
def client():
    with TestClient(create_app()) as test_client:
        yield test_client


# --------------------------------------------------------- состав отчёта


def test_every_decision_has_a_meaning() -> None:
    """Новое решение без пояснения не должно проскочить молча.

    Иначе отчёт по нему упал бы с KeyError уже в проде — на операции,
    которую как раз и надо объяснить.
    """
    assert set(DECISION_MEANING) == set(Decision)


def test_report_answers_what_was_decided_and_why(client) -> None:
    text = client.post("/report", json=transaction()).text

    # Что решено.
    assert "txn_report" in text
    assert "РЕШЕНИЕ: BLOCK" in text
    assert DECISION_MEANING[Decision.BLOCK] in text
    # Почему.
    assert "ПОЧЕМУ" in text
    assert "Сработавшие политики:" in text
    assert "impossible_travel" in text
    # Чем посчитано — без этого отчёт нельзя приложить к делу.
    assert "lightgbm" in text
    assert "shap" in text or "ablation" in text or "lightgbm_native" in text


def test_report_names_the_money_and_the_merchant(client) -> None:
    """Сумма и мерчант есть только в запросе — в ответе API их нет."""
    text = client.post("/report", json=transaction()).text

    assert "45 000.00" in text
    assert "Crypto Exchange (NG)" in text


def test_policies_are_not_listed_twice(client) -> None:
    """`reasons` содержит и политики, и факторы; политики идут отдельно.

    Без вычитания половина отчёта читалась бы дважды подряд, причём
    формулировки политики и одноимённого признака отличаются парой слов —
    это выглядело бы как ошибка, а не как два взгляда на одно.
    """
    payload = client.post("/predict", json=transaction(persist=False)).json()
    text = client.post("/report", json=transaction()).text

    policy_reason = payload["explanation"]["policy_reasons"][0]
    body = text.split("Что увидела модель:")[1].split("Сработавшие политики:")[0]

    assert policy_reason not in body


def test_calm_transaction_says_so_instead_of_leaving_a_hole(client) -> None:
    """Пустой список причин — не сбой, и отчёт обязан это проговорить."""
    text = client.post("/report", json=calm()).text

    assert "РЕШЕНИЕ: APPROVE" in text
    assert "Политики не срабатывали" in text


def test_contributions_table_shows_direction(client) -> None:
    text = client.post("/report", json=transaction()).text

    assert "ВКЛАД ПРИЗНАКОВ" in text
    assert "повышает" in text


def test_report_is_plain_text(client) -> None:
    response = client.post("/report", json=transaction())

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "charset=utf-8" in response.headers["content-type"]


def test_generation_time_can_be_fixed_for_comparison() -> None:
    """Иначе отчёт нельзя было бы сравнить с эталоном: время всегда разное."""
    from app.schemas.prediction import (
        ExplanationOut,
        PredictionResponse,
        ThresholdsOut,
    )
    from app.schemas.transaction import TransactionRequest

    request = TransactionRequest(**transaction())
    response = PredictionResponse(
        transaction_id="txn_report",
        user_id="user_00042",
        timestamp=BASE_TIME,
        risk_score=87,
        model_score=87,
        probability=0.87,
        decision=Decision.BLOCK,
        risk_level="HIGH",
        raised_by_rules=False,
        triggered_rules=[],
        explanation=ExplanationOut(
            method="shap",
            units="logit",
            base_value=0.0,
            summary="сводка",
            reasons=[],
            policy_reasons=[],
            factors=[],
        ),
        thresholds=ThresholdsOut(approve_max=30, challenge_max=70, critical_min=90),
        features={},
        processing_ms=1.0,
    )

    first = render_transaction_report(
        request, response, generated_at=datetime(2026, 9, 20, 12, 0, 0)
    )
    second = render_transaction_report(
        request, response, generated_at=datetime(2026, 9, 20, 12, 0, 0)
    )

    assert first == second
    assert "2026-09-20 12:00:00 UTC" in first
    # Пустое объяснение — не повод оставить дыру в тексте.
    assert "Повышающих риск факторов модель не нашла." in first


def test_unknown_model_does_not_leave_a_blank(client) -> None:
    """Отчёт без метки модели бесполезен, но пустая строка хуже прочерка."""
    from app.schemas.prediction import (
        ExplanationOut,
        PredictionResponse,
        ThresholdsOut,
    )
    from app.schemas.transaction import TransactionRequest

    response = PredictionResponse(
        transaction_id="t",
        user_id="u",
        timestamp=BASE_TIME,
        risk_score=10,
        model_score=10,
        probability=0.1,
        decision=Decision.APPROVE,
        risk_level="LOW",
        raised_by_rules=False,
        triggered_rules=[],
        explanation=ExplanationOut(
            method="ablation",
            units="probability",
            base_value=0.0,
            summary="",
            reasons=[],
            policy_reasons=[],
            factors=[],
        ),
        thresholds=ThresholdsOut(approve_max=30, challenge_max=70, critical_min=90),
        features={},
        processing_ms=1.0,
    )

    text = render_transaction_report(TransactionRequest(**calm()), response)

    assert "неизвестно" in text


# ------------------------------------------------- отчёт ничего не меняет


def test_report_does_not_touch_the_history(client) -> None:
    """Аналитик, перечитавший обоснование трижды, не должен трижды
    добавить операцию в статистику."""
    state = client.app.state.shin
    state.transactions.clear()
    state.profiles.clear()

    for _ in range(3):
        client.post("/report", json=transaction(persist=True))

    assert client.get("/stats").json()["total_transactions"] == 0
    assert client.get("/transactions").json()["total"] == 0


def test_report_does_not_move_the_drift_window(client) -> None:
    state = client.app.state.shin
    if state.drift is None:
        pytest.skip("эталон не выгружен")
    state.drift.reset()

    client.post("/report", json=transaction(persist=True))

    assert client.get("/monitoring/drift").json()["observed_rows"] == 0


def test_report_without_a_model_reports_the_reason(tmp_path) -> None:
    settings = Settings(model_path=str(tmp_path / "missing.joblib"))

    with TestClient(create_app(settings)) as degraded:
        response = degraded.post("/report", json=transaction())

    assert response.status_code == 503
    assert response.json()["error_code"] == "model_not_loaded"
