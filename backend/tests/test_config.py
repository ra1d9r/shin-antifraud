"""Тесты смены порогов на работающей системе.

Пороги меняют не одно число: от них зависит всё, что система уже
успела насчитать. Поэтому проверяется не «значение записалось»,
а согласованность — что поехало следом и, не менее важно, что
намеренно осталось на месте.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config.settings import Settings
from app.main import create_app

#: ASCII намеренно: пароль уходит в заголовок, а HTTP-заголовки
#: не переносят кириллицу. Настройки это теперь и проверяют.
TOKEN = "test-admin-token"


def transaction(**overrides) -> dict:
    body = {
        "user_id": "user_config",
        "amount": 100.0,
        "timestamp": "2026-09-01T14:30:00",
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
        "user_home_country": "KZ",
        "known_device_ids": ["dev_known_1"],
        "previous_ip_address": "85.132.10.55",
        "txn_count_last_hour": 1,
    }
    body.update(overrides)
    return body


def update(**overrides) -> dict:
    body = {"approve_max": 4, "challenge_max": 70, "critical_min": 90, "rules_enabled": True}
    body.update(overrides)
    return body


@pytest.fixture(scope="module")
def client():
    """Приложение с настроенным паролем — иначе запись выключена."""
    with TestClient(create_app(Settings(config_admin_token=TOKEN))) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def restore(client):
    """Пороги общие на модуль, и правка протекла бы в соседние тесты."""
    state = client.app.state.shin
    state.transactions.clear()
    if state.idempotency:
        state.idempotency.clear()
    yield
    settings = state.settings
    client.post(
        "/config/thresholds",
        json=update(
            approve_max=settings.risk_approve_max,
            challenge_max=settings.risk_challenge_max,
            critical_min=settings.risk_critical_min,
            rules_enabled=settings.rules_enabled,
        ),
        headers={"X-Admin-Token": TOKEN},
    )
    state.threshold_changes.clear()
    state.evaluation_stale = False
    state.evaluation_stale_reason = None


# --------------------------------------------------------------- доступ


def test_write_is_disabled_without_a_token() -> None:
    """Адресом, которым ставится approve_max=100, отключается блокировка
    любого мошенничества. У проекта есть публичный стенд."""
    with TestClient(create_app(Settings(config_admin_token=""))) as locked:
        response = locked.post("/config/thresholds", json=update())

        assert response.status_code == 403
        assert response.json()["error_code"] == "config_locked"
        assert "CONFIG_ADMIN_TOKEN" in response.json()["message"]
        # Чтение при этом открыто и честно говорит, что менять нельзя.
        assert locked.get("/config/thresholds").json()["writable"] is False


def test_wrong_token_is_refused(client) -> None:
    response = client.post(
        "/config/thresholds", json=update(), # ASCII: заголовок с кириллицей не отправить вовсе.
        headers={"X-Admin-Token": "wrong-token"},
    )

    assert response.status_code == 403
    assert client.get("/config/thresholds").json()["overridden"] is False


def test_missing_header_is_refused(client) -> None:
    assert client.post("/config/thresholds", json=update()).status_code == 403


# ------------------------------------------------------------- проверки


def test_thresholds_must_increase(client) -> None:
    """Ошибка данных запроса — значит 422 и разбор по полям, как у всех
    остальных некорректных тел, а не 400 из движка."""
    response = client.post(
        "/config/thresholds",
        json=update(approve_max=80, challenge_max=20),
        headers={"X-Admin-Token": TOKEN},
    )

    assert response.status_code == 422
    assert response.json()["error_code"] == "validation_error"


def test_rejected_update_changes_nothing(client) -> None:
    client.post(
        "/config/thresholds",
        json=update(approve_max=95, challenge_max=90),
        headers={"X-Admin-Token": TOKEN},
    )

    assert client.get("/config/thresholds").json()["approve_max"] == 30


# ------------------------------------------------------- смена действует


def test_new_thresholds_change_the_verdict(client) -> None:
    """Главное: решение по той же операции становится другим.

    Проверяется послабление, а не ужесточение: операция с нулевым баллом
    остаётся APPROVE при любом пороге (ноль не больше нуля), и на ней
    ничего бы не увидели.
    """
    # Частота выше обычной: политика velocity_burst даёт балл 60 —
    # достаточно, чтобы система пометила операцию, и достаточно далеко
    # от потолка, чтобы послабление было видно.
    risky = transaction(persist=False, txn_count_last_hour=9)
    before = client.post("/predict", json=risky).json()
    score = before["risk_score"]

    assert before["decision"] != "APPROVE", "нужна операция, которую система помечает"
    # Балл 100 не станет APPROVE ни при какой конфигурации: пороги обязаны
    # возрастать, значит approve_max не больше 99. Это свойство модели
    # порогов, и проверять на нём послабление бессмысленно.
    assert score <= 98, "для проверки нужен балл ниже потолка"

    client.post(
        "/config/thresholds",
        # Поднимаем порог ровно до балла операции: выше — уже не APPROVE.
        json=update(approve_max=score, challenge_max=score + 1, critical_min=score + 2),
        headers={"X-Admin-Token": TOKEN},
    )
    after = client.post("/predict", json=risky).json()

    assert after["decision"] == "APPROVE"
    # Оценка та же — изменилось только то, как её трактуют.
    assert before["risk_score"] == after["risk_score"]


def test_policies_can_be_switched_off(client) -> None:
    client.post(
        "/config/thresholds", json=update(rules_enabled=False), headers={"X-Admin-Token": TOKEN}
    )

    assert client.get("/config/thresholds").json()["rules_enabled"] is False
    assert client.get("/health").json()["rules_enabled"] is True  # настройка из .env


def test_history_records_who_and_why(client) -> None:
    client.post(
        "/config/thresholds",
        json=update(changed_by="ahmetova", reason="дно кривой компромисса"),
        headers={"X-Admin-Token": TOKEN},
    )

    state = client.get("/config/thresholds").json()

    assert state["overridden"] is True
    assert state["changed_at"] is not None
    assert state["history"][0]["changed_by"] == "ahmetova"
    assert state["history"][0]["reason"] == "дно кривой компромисса"
    # Значения из .env остаются видны: к ним вернёт перезапуск.
    assert state["env_defaults"]["approve_max"] == 30


# --------------------------------- что поехало следом, а что осталось


def test_shadow_comparison_is_reset(client) -> None:
    """Тень сравнивает две конфигурации: если одна изменилась посреди
    набора, матрица смешивает разное."""
    state = client.app.state.shin
    if state.shadow is None:
        pytest.skip("теневой режим выключен")

    client.post("/predict", json=transaction(transaction_id="txn_before"))
    assert client.get("/monitoring/shadow").json()["observed"] == 1

    applied = client.post(
        "/config/thresholds", json=update(), headers={"X-Admin-Token": TOKEN}
    ).json()

    assert applied["shadow_reset"] is True
    assert client.get("/monitoring/shadow").json()["observed"] == 0


def test_shadow_rederives_what_it_inherits(client) -> None:
    """Незаданные пороги тень наследует у основной.

    Без пересборки она осталась бы отличаться не тем, чем задумано:
    наследование вывелось бы от прежних значений.
    """
    state = client.app.state.shin
    if state.shadow is None:
        pytest.skip("теневой режим выключен")

    client.post(
        "/config/thresholds",
        json=update(approve_max=11, challenge_max=55, critical_min=80),
        headers={"X-Admin-Token": TOKEN},
    )

    shadow = client.get("/monitoring/shadow").json()["shadow"]
    assert shadow["approve_max"] == 11
    assert shadow["challenge_max"] == 55


def test_analytics_is_marked_stale(client) -> None:
    """Отчёт посчитан на прежних порогах. Скрывать числа хуже, чем
    показать их с пометкой."""
    applied = client.post(
        "/config/thresholds", json=update(), headers={"X-Admin-Token": TOKEN}
    ).json()

    assert applied["analytics_marked_stale"] is True
    overview = client.get("/analytics/overview").json()
    assert overview["stale"] is True
    assert "Пороги изменены" in overview["stale_reason"]


def test_drift_is_deliberately_kept(client) -> None:
    """Дрейф сравнивает распределение входных признаков, а пороги
    на признаки не влияют вовсе. Обнулить его значило бы выбросить
    исправные наблюдения за компанию."""
    state = client.app.state.shin
    if state.drift is None:
        pytest.skip("эталон не выгружен")
    state.drift.reset()

    client.post("/predict", json=transaction(transaction_id="txn_drift_keep"))
    applied = client.post(
        "/config/thresholds", json=update(), headers={"X-Admin-Token": TOKEN}
    ).json()

    assert applied["drift_kept"] is True
    assert client.get("/monitoring/drift").json()["observed_rows"] == 1


def test_history_survives_but_stats_admits_the_change(client) -> None:
    """Историю не чистим: в ней операции, которые аналитику ещё
    размечать, и по ней же строится граф связей. Но молчать нельзя."""
    client.post("/predict", json=transaction(transaction_id="txn_kept"))
    client.post("/config/thresholds", json=update(), headers={"X-Admin-Token": TOKEN})

    stats = client.get("/stats").json()

    assert stats["total_transactions"] == 1
    assert stats["thresholds_changed_at"] is not None


def test_stats_is_quiet_when_nothing_changed(client) -> None:
    assert client.get("/stats").json()["thresholds_changed_at"] is None


# ----------------------------------------------------------- перезапуск


def test_restart_returns_to_the_env_values() -> None:
    """Неудачную правку отменяет рестарт, а не поиск того, кто её сделал."""
    settings = Settings(config_admin_token=TOKEN)

    with TestClient(create_app(settings)) as first:
        first.post(
            "/config/thresholds",
            json=update(approve_max=1, challenge_max=2, critical_min=3),
            headers={"X-Admin-Token": TOKEN},
        )
        assert first.get("/config/thresholds").json()["approve_max"] == 1

    with TestClient(create_app(settings)) as second:
        state = second.get("/config/thresholds").json()

    assert state["approve_max"] == settings.risk_approve_max
    assert state["overridden"] is False
