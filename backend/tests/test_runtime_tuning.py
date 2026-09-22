"""Настройка политик и бизнес-метрики на работающей системе.

Брифинг §4.5 требует возможности «корректировать веса рисков»,
§5.C — «гибкую настраиваемую бизнес-метрику». Оба места легко
изобразить: завести эндпоинт, записать значение в настройки и вернуть
200. Снаружи выглядит одинаково, а системы это не касается.

Поэтому проверяется не «значение записалось», а что оно **что-то
меняет**: у политик — решение по той же операции, у метрики — кривую
компромисса и оптимальный порог на дашборде. И отдельно — что каждая
из настроек НЕ трогает то, к чему отношения не имеет.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config.settings import Settings
from app.main import create_app

TOKEN = "test-admin-token"
HEADERS = {"X-Admin-Token": TOKEN}


def transaction(**overrides) -> dict:
    """Операция, на которой срабатывает ровно одна политика — new_device.

    Незнакомое устройство И незнакомая сеть: составное условие политики
    выполнено, всё остальное привычно. Одна политика вместо нескольких
    нужна, чтобы подъём её порога было видно в оценке без примеси.
    """
    body = {
        "user_id": "u_tune",
        "amount": 100.0,
        "timestamp": "2026-09-01T14:30:00",
        "merchant": "Magnum",
        "country": "KZ",
        "device_id": "dev_new_99",
        "ip_address": "203.0.113.7",
        "latitude": 51.16,
        "longitude": 71.44,
        "transaction_frequency": 3,
        "previous_transaction_amount": 95.0,
        "previous_transaction_country": "KZ",
        "account_age_days": 800,
        "user_avg_amount": 100.0,
        "user_home_country": "KZ",
        "known_device_ids": ["dev_known_1"],
        "previous_ip_address": "85.132.10.55",
        "persist": False,
    }
    body.update(overrides)
    return body


@pytest.fixture(scope="module")
def client():
    with TestClient(create_app(Settings(config_admin_token=TOKEN))) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def restore(client):
    """Настройки общие на модуль, и правка протекла бы в соседние тесты."""
    state = client.app.state.shin
    before_settings = state.settings
    before_engine = state.risk_engine
    before_evaluation = state.evaluation
    before_stale = state.evaluation_stale
    yield
    state.settings = before_settings
    state.risk_engine = before_engine
    state.evaluation = before_evaluation
    state.evaluation_stale = before_stale
    state.policy_changed_at = None
    state.cost_changed_at = None
    if state.service is not None:
        state.service.replace_risk_engine(before_engine)


# ------------------------------------------- политики (брифинг §4.5)


def test_policy_thresholds_are_readable_without_a_password(client) -> None:
    """Те же значения видны в каждом ответе /predict — прятать нечего."""
    payload = client.get("/config/policies").json()

    assert payload["policies"], "ни одной политики"
    assert all(0 <= item["min_score"] <= 100 for item in payload["policies"])
    assert payload["overridden"] is False


def test_raising_a_policy_changes_the_verdict(client) -> None:
    """Главная проверка §4.5: настройка меняет решение, а не только поле."""
    before = client.post("/predict", json=transaction()).json()
    assert [rule["key"] for rule in before["triggered_rules"]] == ["new_device"]

    applied = client.post(
        "/config/policies",
        json={"new_device_min_score": 85, "changed_by": "тест"},
        headers=HEADERS,
    )
    assert applied.status_code == 200

    after = client.post("/predict", json=transaction()).json()

    assert after["risk_score"] > before["risk_score"]
    assert after["risk_score"] == 85
    assert before["decision"] == "CHALLENGE"
    assert after["decision"] == "BLOCK"


def test_lowering_a_policy_gives_the_model_its_say_back(client) -> None:
    """Опущенный порог политики перестаёт перебивать оценку модели."""
    client.post("/config/policies", json={"new_device_min_score": 0}, headers=HEADERS)

    after = client.post("/predict", json=transaction()).json()

    # Политика всё ещё срабатывает — условие не изменилось, — но
    # поднимать оценку ей больше нечем.
    assert [rule["key"] for rule in after["triggered_rules"]] == ["new_device"]
    assert after["risk_score"] < 35


def test_untouched_policies_keep_their_thresholds(client) -> None:
    """Настраивают одну политику; остальные пять трогать не просили."""
    before = {p["key"]: p["min_score"] for p in client.get("/config/policies").json()["policies"]}

    client.post("/config/policies", json={"new_device_min_score": 80}, headers=HEADERS)
    after = {p["key"]: p["min_score"] for p in client.get("/config/policies").json()["policies"]}

    assert after["new_device"] == 80
    for key, value in before.items():
        if key != "new_device":
            assert after[key] == value, f"{key} изменилась, хотя её не трогали"


def test_policy_change_resets_the_shadow_and_ages_the_analytics(client) -> None:
    """Те же последствия, что у смены порогов, и по тем же причинам."""
    body = client.post(
        "/config/policies", json={"velocity_min_score": 70}, headers=HEADERS
    ).json()

    assert body["shadow_reset"] is True
    assert body["analytics_marked_stale"] is True
    assert body["state"]["overridden"] is True
    assert body["state"]["changed_at"] is not None


def test_empty_policy_update_is_refused(client) -> None:
    """Пустое тело меняет ноль величин и молча ответило бы успехом."""
    response = client.post("/config/policies", json={}, headers=HEADERS)

    assert response.status_code == 422


@pytest.mark.parametrize("headers", [{}, {"X-Admin-Token": "wrong"}])
def test_policy_write_needs_the_password(client, headers) -> None:
    response = client.post("/config/policies", json={"new_device_min_score": 10}, headers=headers)

    assert response.status_code == 403


def test_policy_score_out_of_range_is_refused(client) -> None:
    response = client.post(
        "/config/policies", json={"new_device_min_score": 101}, headers=HEADERS
    )

    assert response.status_code == 422


# --------------------------------- бизнес-метрика стоимости (брифинг §5.C)


def optimum(client) -> int:
    return client.get("/analytics/overview").json()["optimal_threshold"]


def test_cost_weights_are_readable_without_a_password(client) -> None:
    payload = client.get("/config/cost").json()

    assert payload["fraud_loss_ratio"] >= 0
    assert payload["false_challenge"] >= 0
    assert payload["overridden"] is False


def test_expensive_checks_move_the_optimum_up(client) -> None:
    """Главная проверка §5.C: метрика меняется — кривая едет следом.

    Сделать лишнюю проверку в десять раз дороже значит сказать системе
    «беспокоить клиента — дорого». Оптимальный порог обязан подняться:
    проверять меньше, пропускать больше.
    """
    before = optimum(client)

    applied = client.post(
        "/config/cost", json={"false_challenge": 120.0}, headers=HEADERS
    ).json()

    assert applied["curve_recomputed"] is True
    assert applied["optimal_threshold_before"] == before
    assert applied["optimal_threshold_after"] > before
    assert optimum(client) == applied["optimal_threshold_after"]


def test_free_fraud_stops_the_system_from_checking(client) -> None:
    """Крайний случай, где ответ известен заранее.

    Если пропущенный фрод не стоит ничего, любая проверка — чистый
    убыток, и дешевле всего почти никого не проверять.

    Порог сравнивается с исходным, а не с числом: прибитое гвоздём
    значение откалибровано на конкретной модели и падает при первом же
    переобучении, ничего при этом не проверив. Здесь проверяется
    направление — метрика сказала «проверки дороги», порог обязан
    уехать вверх.
    """
    before = optimum(client)

    client.post(
        "/config/cost",
        json={"fraud_loss_ratio": 0.0, "fraud_fixed": 0.0},
        headers=HEADERS,
    )

    after = optimum(client)
    assert after > before, "даровой фрод не сдвинул порог вверх"
    assert after >= 80, f"порог {after}: система всё ещё проверяет слишком многих"


def test_expensive_fraud_makes_the_system_check_everyone(client) -> None:
    """Обратный крайний случай — иначе тест выше прошёл бы и на заглушке,
    которая всегда возвращает большое число."""
    before = optimum(client)

    client.post("/config/cost", json={"fraud_loss_ratio": 5.0}, headers=HEADERS)

    after = optimum(client)
    assert after <= before, "дорогой фрод не сдвинул порог вниз"
    assert after <= 10, f"порог {after}: система всё ещё пропускает слишком многих"


def test_recomputed_analytics_is_not_marked_stale(client) -> None:
    """Пересчитанные числа не устарели — они посчитаны только что.

    Пометить их было бы проще, но человек, настроивший метрику, хочет
    увидеть новый оптимум, а не предложение выгрузить отчёт заново —
    в проде нечем: датасета в образе нет.
    """
    client.post("/config/cost", json={"false_challenge": 60.0}, headers=HEADERS)

    assert client.get("/analytics/overview").json()["stale"] is False


def test_cost_weights_never_touch_the_verdict(client) -> None:
    """Веса переводят решения в деньги, а не участвуют в их принятии."""
    before = client.post("/predict", json=transaction()).json()

    client.post(
        "/config/cost",
        json={"fraud_loss_ratio": 9.0, "false_block": 1.0, "false_challenge": 300.0},
        headers=HEADERS,
    )
    after = client.post("/predict", json=transaction()).json()

    assert after["decision"] == before["decision"]
    assert after["risk_score"] == before["risk_score"]
    assert after["features"] == before["features"]


def test_repricing_with_the_same_weights_changes_nothing(client) -> None:
    """Пересчёт на тех же весах обязан дать ту же кривую.

    Разойдись он — значит формула пересчёта не та, по которой отчёт
    собирали, и все остальные проверки меряли бы не то.
    """
    current = client.get("/config/cost").json()
    before = client.get("/analytics/overview").json()["curve"]

    client.post(
        "/config/cost",
        json={"false_challenge": current["false_challenge"]},
        headers=HEADERS,
    )
    after = client.get("/analytics/overview").json()["curve"]

    assert after == before


def test_old_report_without_amounts_refuses_to_pretend(client) -> None:
    """Отчёт, выгруженный до появления сумм, пересчитать нечем.

    Молча оставить старые числа и ответить успехом значило бы показывать
    на дашборде одну метрику, а в настройках другую.
    """
    state = client.app.state.shin
    state.evaluation = {
        **state.evaluation,
        "curve": [
            {key: value for key, value in point.items() if key != "fraud_missed_amount"}
            for point in state.evaluation["curve"]
        ],
    }

    assert client.get("/config/cost").json()["curve_recomputable"] is False

    applied = client.post(
        "/config/cost", json={"false_challenge": 999.0}, headers=HEADERS
    ).json()

    assert applied["curve_recomputed"] is False
    assert applied["optimal_threshold_after"] is None
    # Веса всё равно приняты: следующая выгрузка посчитает по ним.
    assert applied["state"]["false_challenge"] == 999.0


def test_empty_cost_update_is_refused(client) -> None:
    assert client.post("/config/cost", json={}, headers=HEADERS).status_code == 422


@pytest.mark.parametrize("headers", [{}, {"X-Admin-Token": "wrong"}])
def test_cost_write_needs_the_password(client, headers) -> None:
    response = client.post("/config/cost", json={"false_challenge": 1.0}, headers=headers)

    assert response.status_code == 403


def test_negative_cost_is_refused(client) -> None:
    """Отрицательная стоимость означала бы, что ошибка приносит прибыль."""
    response = client.post("/config/cost", json={"false_challenge": -1.0}, headers=HEADERS)

    assert response.status_code == 422
