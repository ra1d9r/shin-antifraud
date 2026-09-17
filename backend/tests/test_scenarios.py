"""Тесты сценариев ручного тестирования (ТЗ §9).

Главное здесь — не «эндпоинт отвечает», а то, ради чего сценарии написаны:
Risk Score обязан расти от безобидной покупки к явной атаке, и этот рост
должен быть воспроизводимым.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.schemas.enums import Decision, ScenarioKey
from app.services.scenarios import SCENARIOS, get_scenario, scenario_order


@pytest.fixture(scope="module")
def client():
    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def clean_state(client):
    state = client.app.state.shin
    state.transactions.clear()
    state.profiles.clear()
    yield


def run_all(client) -> dict[str, dict]:
    """Прогнать все сценарии и вернуть ответы по ключам."""
    return {
        key.value: client.post(f"/scenarios/{key.value}/run").json()
        for key in scenario_order()
    }


# ------------------------------------------------------ состав сценариев


def test_all_five_scenarios_are_defined() -> None:
    """ТЗ §9 перечисляет ровно пять сценариев."""
    assert len(SCENARIOS) == 5
    assert {scenario.key for scenario in SCENARIOS} == set(ScenarioKey)


def test_scenarios_share_one_customer_profile() -> None:
    """Сравнивать Risk Score можно только у одного и того же клиента."""
    profiles = {
        (
            scenario.request["user_id"],
            scenario.request["user_avg_amount"],
            scenario.request["user_home_country"],
            tuple(scenario.request["known_device_ids"]),
            scenario.request["account_age_days"],
        )
        for scenario in SCENARIOS
    }
    assert len(profiles) == 1, "сценарии описывают разных клиентов — сравнение бессмысленно"


def test_scenarios_declare_what_they_change() -> None:
    normal = get_scenario(ScenarioKey.NORMAL)
    assert normal.changed_from_normal == ()

    for scenario in SCENARIOS:
        if scenario.key is ScenarioKey.NORMAL:
            continue
        assert scenario.changed_from_normal, f"{scenario.key}: не указано, что изменено"
        for field in scenario.changed_from_normal:
            assert scenario.request[field] != normal.request[field], (
                f"{scenario.key}: поле {field} заявлено как изменённое, но совпадает с обычным"
            )


def test_scenario_requests_are_valid_transactions() -> None:
    """Тело каждого сценария обязано проходить валидацию схемы."""
    for scenario in SCENARIOS:
        transaction = scenario.to_transaction()
        assert transaction.user_id
        assert transaction.amount > 0


def test_scenarios_pin_their_timestamps() -> None:
    """Фиксированное время — условие воспроизводимости чисел в документации."""
    for scenario in SCENARIOS:
        assert scenario.request["timestamp"], f"{scenario.key}: время не зафиксировано"
        assert scenario.request["previous_timestamp"]


# ----------------------------------------------------------- эндпоинты


def test_list_scenarios_returns_all(client) -> None:
    items = client.get("/scenarios").json()["items"]
    assert len(items) == 5
    for item in items:
        assert item["title"] and item["description"] and item["expectation"]
        assert item["transaction"]["user_id"]


def test_read_single_scenario(client) -> None:
    payload = client.get("/scenarios/new_device").json()
    assert payload["key"] == "new_device"
    assert payload["transaction"]["device_id"] == "dev_unknown_77"


def test_unknown_scenario_is_rejected(client) -> None:
    assert client.get("/scenarios/no_such_case").status_code == 422


# ------------------------------------------------- поведение по ТЗ §9


def test_risk_grows_from_normal_to_attack(client) -> None:
    """Ключевое требование ТЗ §9: риск растёт от сценария 1 к сценарию 5."""
    results = run_all(client)
    scores = [results[key.value]["risk_score"] for key in scenario_order()]

    assert scores == sorted(scores), f"риск не растёт монотонно: {scores}"
    assert scores[0] < scores[-1]


def test_scenario_1_is_approved(client) -> None:
    payload = client.post("/scenarios/normal/run").json()
    assert payload["decision"] == Decision.APPROVE.value
    assert payload["risk_score"] <= payload["thresholds"]["approve_max"]


def test_scenario_2_raises_score_above_normal(client) -> None:
    """ТЗ §9.2: «Risk Score должен увеличиться»."""
    normal = client.post("/scenarios/normal/run").json()
    new_device = client.post("/scenarios/new_device/run").json()

    assert new_device["risk_score"] > normal["risk_score"]
    assert any(rule["key"] == "new_device" for rule in new_device["triggered_rules"])


def test_scenario_3_raises_score_above_normal(client) -> None:
    """ТЗ §9.3: «повышенный риск»."""
    normal = client.post("/scenarios/normal/run").json()
    country = client.post("/scenarios/unusual_country/run").json()

    assert country["risk_score"] > normal["risk_score"]
    assert country["decision"] != Decision.APPROVE.value


def test_scenario_4_raises_score_above_normal(client) -> None:
    """ТЗ §9.4: «повышенный риск»."""
    normal = client.post("/scenarios/normal/run").json()
    large = client.post("/scenarios/large_amount/run").json()

    assert large["risk_score"] > normal["risk_score"]
    assert large["decision"] != Decision.APPROVE.value


def test_scenario_4_is_caught_by_model_alone(client) -> None:
    """Крупную сумму распознаёт сама модель, без помощи политик.

    Это важно показать: иначе система выглядела бы набором правил,
    а не работающей моделью.
    """
    payload = client.post("/scenarios/large_amount/run").json()
    assert payload["triggered_rules"] == []
    assert payload["model_score"] == payload["risk_score"]


def test_scenario_5_is_blocked(client) -> None:
    """ТЗ §9.5: «высокий Risk Score / BLOCK»."""
    payload = client.post("/scenarios/multiple_anomalies/run").json()

    assert payload["decision"] == Decision.BLOCK.value
    assert payload["risk_score"] > payload["thresholds"]["challenge_max"]
    assert len(payload["triggered_rules"]) >= 3


def test_every_scenario_is_explained(client) -> None:
    """ТЗ §7: у каждого решения от 3 до 5 факторов и хотя бы одна причина."""
    for payload in run_all(client).values():
        explanation = payload["explanation"]
        assert 3 <= len(explanation["factors"]) <= 5
        assert explanation["summary"]
        assert explanation["reasons"]


# ------------------------------------------------------ воспроизводимость


def test_scenario_results_are_reproducible(client) -> None:
    """Повторный прогон обязан дать тот же ответ.

    Сценарии передают профиль явно, поэтому накопленная история на них
    не влияет. Без этого свойства демонстрация выглядела бы как дефект:
    два нажатия — два разных числа.
    """
    first = run_all(client)
    second = run_all(client)

    for key in first:
        assert first[key]["risk_score"] == second[key]["risk_score"], key
        assert first[key]["features"] == second[key]["features"], key


def test_persist_flag_controls_history(client) -> None:
    client.post("/scenarios/normal/run", params={"persist": False})
    assert client.get("/stats").json()["total_transactions"] == 0

    client.post("/scenarios/normal/run")
    assert client.get("/stats").json()["total_transactions"] == 1


def test_running_scenarios_fills_dashboard_statistics(client) -> None:
    """Прогон сценариев наполняет Overview — это штатный путь демонстрации."""
    run_all(client)
    stats = client.get("/stats").json()

    assert stats["total_transactions"] == 5
    assert stats["blocked_transactions"] >= 1
    assert stats["suspicious_transactions"] >= 1
    assert stats["average_risk_score"] > 0
    assert stats["triggered_rules"]
