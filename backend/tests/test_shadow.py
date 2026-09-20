"""Тесты теневого режима.

Главное свойство здесь не «считает правильно», а **«не влияет»**. Вторая
конфигурация видит настоящие операции живых клиентов, и единственная
причина, по которой это допустимо, — что её решения никуда не уходят.
Поэтому первым делом проверяется именно это.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config.settings import Settings
from app.main import create_app
from app.monitoring.shadow import RECENT_LIMIT, ShadowConfig, ShadowRunner
from app.risk_engine.engine import RiskEngine, RiskThresholds
from app.schemas.enums import Decision

BASE_TIME = "2026-09-01T14:30:00"


def transaction(**overrides) -> dict:
    body = {
        "user_id": "user_shadow",
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
        "user_avg_amount": 100.0,
        "user_home_country": "KZ",
        "known_device_ids": ["dev_known_1"],
        "previous_ip_address": "85.132.10.55",
        "txn_count_last_hour": 1,
    }
    body.update(overrides)
    return body


def engine(approve_max: int = 30, challenge_max: int = 70, rules_enabled: bool = True) -> RiskEngine:
    return RiskEngine(
        thresholds=RiskThresholds(
            approve_max=approve_max, challenge_max=challenge_max, critical_min=90
        ),
        rules=(),
        rules_enabled=rules_enabled,
    )


def runner_of(primary: RiskEngine, shadow: RiskEngine) -> ShadowRunner:
    return ShadowRunner(
        engine=shadow,
        config=ShadowConfig(thresholds=shadow.thresholds, rules_enabled=shadow.rules_enabled),
        primary=primary,
    )


def feed(runner: ShadowRunner, primary: RiskEngine, probability: float, amount: float = 100.0,
         txn: str = "txn") -> None:
    runner.observe(
        primary=primary.assess(probability),
        shadow=runner.assess(probability, None),
        transaction_id=txn,
        user_id="u",
        amount=amount,
    )


# ============================================ главное: тень не влияет ====


@pytest.fixture(scope="module")
def client():
    with TestClient(create_app()) as test_client:
        yield test_client


def test_shadow_does_not_change_the_answer() -> None:
    """Ответ обязан быть тем же с тенью и без неё, до последнего поля.

    Это не просто регрессия, а условие допустимости всей затеи: вторая
    конфигурация смотрит на операции настоящих клиентов, и оправдано это
    ровно тем, что её решения никуда не уходят.
    """
    quiet = Settings(shadow_enabled=False)
    loud = Settings(shadow_enabled=True, shadow_rules_enabled=False, shadow_approve_max=1)

    # Идентификатор задаётся явно: без него схема генерирует случайный,
    # и два ответа разошлись бы по нему, ничего не сказав о тени.
    body = transaction(transaction_id="txn_same")
    with TestClient(create_app(quiet)) as without, TestClient(create_app(loud)) as with_shadow:
        first = without.post("/predict", json=body).json()
        second = with_shadow.post("/predict", json=body).json()

    # Время обработки заведомо разное — сравнивать его бессмысленно.
    first.pop("processing_ms")
    second.pop("processing_ms")
    assert first == second


def test_shadow_decisions_stay_out_of_history_and_stats(client) -> None:
    """В истории и статистике — только то, что система решила на самом деле."""
    state = client.app.state.shin
    state.transactions.clear()
    if state.shadow is None:
        pytest.skip("теневой режим выключен")

    client.post("/predict", json=transaction(transaction_id="txn_only_once"))

    rows = client.get("/transactions").json()
    assert rows["total"] == 1
    assert client.get("/stats").json()["total_transactions"] == 1
    # Тень при этом операцию видела.
    assert client.get("/monitoring/shadow").json()["observed"] >= 1


def test_what_if_mode_does_not_reach_the_shadow(client) -> None:
    state = client.app.state.shin
    if state.shadow is None:
        pytest.skip("теневой режим выключен")
    state.shadow.reset()

    client.post("/predict", json=transaction(persist=False))

    assert client.get("/monitoring/shadow").json()["observed"] == 0


# ================================================== конфигурация тени ====


def test_unset_thresholds_are_inherited_from_the_primary() -> None:
    """Иначе получилось бы второе место, где пороги разъезжаются с основными."""
    settings = Settings(
        risk_approve_max=30,
        risk_challenge_max=70,
        risk_critical_min=90,
        shadow_approve_max=5,
    )

    config = ShadowConfig.from_settings(settings)

    assert config.thresholds.approve_max == 5
    assert config.thresholds.challenge_max == 70
    assert config.thresholds.critical_min == 90


def test_difference_is_described_in_words() -> None:
    primary = engine(approve_max=30, rules_enabled=True)
    shadow = engine(approve_max=4, rules_enabled=False)

    description = runner_of(primary, shadow).report().difference

    assert "30" in description and "4" in description
    assert "политики выключены" in description


def test_identical_configuration_is_called_out() -> None:
    """Стопроцентное согласие с самим собой нельзя показывать как достижение."""
    primary = engine()
    report = runner_of(primary, engine()).report()

    assert report.differs is False
    assert report.difference == "совпадает с основной"


def test_broken_shadow_thresholds_do_not_stop_the_application() -> None:
    """Кривые пороги в .env не должны стоить работающей системы."""
    settings = Settings(shadow_approve_max=80, shadow_challenge_max=20)

    with TestClient(create_app(settings)) as degraded:
        assert degraded.post("/predict", json=transaction()).status_code == 200
        response = degraded.get("/monitoring/shadow")

    assert response.status_code == 503
    assert response.json()["error_code"] == "shadow_unavailable"


def test_disabled_shadow_says_why() -> None:
    with TestClient(create_app(Settings(shadow_enabled=False))) as off:
        response = off.get("/monitoring/shadow")

    assert response.status_code == 503
    assert "SHADOW_ENABLED" in response.json()["message"]


# ======================================================== сравнение ====


def test_nothing_observed_means_unknown_not_zero() -> None:
    report = runner_of(engine(), engine(approve_max=4)).report()

    assert report.observed == 0
    assert report.agreement_share is None


def test_matrix_counts_pairs_of_decisions() -> None:
    primary = engine(approve_max=30, challenge_max=70)
    shadow = engine(approve_max=4, challenge_max=70)
    runner = runner_of(primary, shadow)

    feed(runner, primary, 0.20)  # основная APPROVE, теневая CHALLENGE
    feed(runner, primary, 0.02)  # обе APPROVE
    feed(runner, primary, 0.90)  # обе BLOCK

    report = runner.report()
    cells = {(cell.primary, cell.shadow): cell.count for cell in report.matrix}

    assert cells[(Decision.APPROVE, Decision.CHALLENGE)] == 1
    assert cells[(Decision.APPROVE, Decision.APPROVE)] == 1
    assert cells[(Decision.BLOCK, Decision.BLOCK)] == 1
    assert (report.agreed, report.disagreed) == (2, 1)
    assert report.agreement_share == round(2 / 3, 4)


def test_loosening_is_counted_as_freed_money() -> None:
    """Тень мягче: часть операций перестала бы попадать под проверку."""
    primary = engine(approve_max=30)
    shadow = engine(approve_max=60)
    runner = runner_of(primary, shadow)

    feed(runner, primary, 0.50, amount=700.0)  # основная CHALLENGE, теневая APPROVE
    feed(runner, primary, 0.50, amount=300.0)

    report = runner.report()

    assert (report.freed_count, report.freed_amount) == (2, 1000.0)
    assert (report.tightened_count, report.tightened_amount) == (0, 0.0)


def test_tightening_is_counted_separately() -> None:
    """Обратная сторона: тень строже, и трения стало бы больше."""
    primary = engine(approve_max=60)
    shadow = engine(approve_max=30)
    runner = runner_of(primary, shadow)

    feed(runner, primary, 0.50, amount=450.0)

    report = runner.report()

    assert (report.tightened_count, report.tightened_amount) == (1, 450.0)
    assert report.freed_count == 0


def test_moving_between_challenge_and_block_is_not_freeing() -> None:
    """И CHALLENGE, и BLOCK означают «система считает операцию подозрительной».

    Перевод из одного в другое меняет строгость, но трение остаётся,
    и записывать это в снятое было бы подтасовкой.
    """
    primary = engine(approve_max=30, challenge_max=40)
    shadow = engine(approve_max=30, challenge_max=70)
    runner = runner_of(primary, shadow)

    feed(runner, primary, 0.50, amount=900.0)  # BLOCK против CHALLENGE

    report = runner.report()

    assert report.disagreed == 1
    assert report.freed_count == 0
    assert report.tightened_count == 0


def test_recent_disagreements_are_bounded_and_newest_first() -> None:
    primary = engine(approve_max=30)
    shadow = engine(approve_max=60)
    runner = runner_of(primary, shadow)

    for index in range(RECENT_LIMIT + 10):
        feed(runner, primary, 0.50, txn=f"txn_{index}")

    recent = runner.report().recent

    assert len(recent) == RECENT_LIMIT
    assert recent[0].transaction_id == f"txn_{RECENT_LIMIT + 9}"
    assert recent[0].primary_decision is Decision.CHALLENGE
    assert recent[0].shadow_decision is Decision.APPROVE


def test_agreement_is_not_recorded_as_a_disagreement() -> None:
    primary = engine()
    runner = runner_of(primary, engine())

    feed(runner, primary, 0.50)

    assert runner.report().recent == ()


def test_reset_clears_the_window() -> None:
    primary = engine(approve_max=30)
    runner = runner_of(primary, engine(approve_max=60))
    feed(runner, primary, 0.50)

    runner.reset()
    report = runner.report()

    assert (report.observed, report.disagreed) == (0, 0)
    assert report.recent == ()
