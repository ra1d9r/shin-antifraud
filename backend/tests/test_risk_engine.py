"""Тесты Risk Engine (ТЗ §6).

Три вещи, ради которых эти тесты существуют:

1. Пороги действительно берутся из конфигурации, а не зашиты в код.
2. Правила только поднимают оценку и никогда её не снижают.
3. Границы решений соблюдаются точно, включая сами пороговые значения.
"""

from __future__ import annotations

import pytest

from app.config.settings import Settings
from app.core.exceptions import InvalidConfigurationError
from app.risk_engine import RiskEngine, RiskThresholds, probability_to_score
from app.risk_engine.rules import build_rules, evaluate_rules, minimum_score
from app.schemas.enums import Decision, RiskLevel

DEFAULT_THRESHOLDS = RiskThresholds(approve_max=30, challenge_max=70, critical_min=90)

# Значения, на которые опираются проверки ниже. Передаются в конструктор явно,
# потому что аргументы конструктора имеют приоритет над .env и переменными
# окружения: иначе правка порогов в .env ломала бы тесты без причины.
HERMETIC_SETTINGS: dict = {
    "risk_approve_max": 30,
    "risk_challenge_max": 70,
    "risk_critical_min": 90,
    "rules_enabled": True,
    "rule_impossible_travel_min_score": 75,
    "rule_high_risk_country_min_score": 55,
    "rule_unusual_country_min_score": 40,
    "rule_new_device_min_score": 35,
    "rule_velocity_min_score": 60,
    "rule_new_account_amount_min_score": 60,
    "rule_velocity_txn_per_hour": 6,
    "rule_new_account_amount_ratio": 4.0,
}


def make_settings(**overrides) -> Settings:
    """Настройки с явными значениями — тест не зависит от окружения."""
    return Settings(**{**HERMETIC_SETTINGS, **overrides})


def make_engine(**overrides) -> RiskEngine:
    return RiskEngine.from_settings(make_settings(**overrides))


def features(**overrides) -> dict[str, float]:
    """Признаки обычной безопасной транзакции."""
    base = {
        "is_impossible_travel": 0.0,
        "is_high_risk_country": 0.0,
        "is_unusual_country": 0.0,
        "is_new_device": 0.0,
        "is_new_account": 0.0,
        "ip_subnet_changed": 0.0,
        "txn_count_last_hour": 1.0,
        "amount_deviation_ratio": 1.0,
    }
    base.update(overrides)
    return base


# ------------------------------------------------ вероятность -> оценка


def test_probability_bounds_map_to_score_bounds() -> None:
    """DoD: probability=0 -> 0, probability=1 -> 100."""
    assert probability_to_score(0.0) == 0
    assert probability_to_score(1.0) == 100


def test_score_is_monotonic() -> None:
    scores = [probability_to_score(p / 20) for p in range(21)]
    assert scores == sorted(scores)


def test_score_uses_arithmetic_rounding() -> None:
    """Встроенный round использует банковское округление — здесь это недопустимо."""
    assert probability_to_score(0.005) == 1  # round(0.5) вернул бы 0
    assert probability_to_score(0.025) == 3  # round(2.5) вернул бы 2
    assert probability_to_score(0.305) == 31


def test_score_clamps_out_of_range_probability() -> None:
    assert probability_to_score(-0.5) == 0
    assert probability_to_score(1.7) == 100


def test_score_rejects_nan() -> None:
    with pytest.raises(InvalidConfigurationError):
        probability_to_score(float("nan"))


# ------------------------------------------------------------- пороги


def test_thresholds_reject_non_increasing_values() -> None:
    with pytest.raises(InvalidConfigurationError):
        RiskThresholds(approve_max=70, challenge_max=30, critical_min=90)
    with pytest.raises(InvalidConfigurationError):
        RiskThresholds(approve_max=30, challenge_max=30, critical_min=90)


def test_thresholds_reject_critical_below_challenge() -> None:
    with pytest.raises(InvalidConfigurationError):
        RiskThresholds(approve_max=30, challenge_max=70, critical_min=60)


def test_decision_boundaries_are_inclusive_at_thresholds() -> None:
    """Само пороговое значение относится к нижнему диапазону (ТЗ §6)."""
    engine = RiskEngine(DEFAULT_THRESHOLDS)
    assert engine.decide(0) is Decision.APPROVE
    assert engine.decide(30) is Decision.APPROVE
    assert engine.decide(31) is Decision.CHALLENGE
    assert engine.decide(70) is Decision.CHALLENGE
    assert engine.decide(71) is Decision.BLOCK
    assert engine.decide(100) is Decision.BLOCK


def test_risk_levels_follow_thresholds() -> None:
    engine = RiskEngine(DEFAULT_THRESHOLDS)
    assert engine.level(0) is RiskLevel.LOW
    assert engine.level(30) is RiskLevel.LOW
    assert engine.level(31) is RiskLevel.MEDIUM
    assert engine.level(70) is RiskLevel.MEDIUM
    assert engine.level(71) is RiskLevel.HIGH
    assert engine.level(89) is RiskLevel.HIGH
    assert engine.level(90) is RiskLevel.CRITICAL


def test_thresholds_come_from_configuration() -> None:
    """DoD: пороги меняются через конфигурацию без правки кода."""
    strict = make_engine(risk_approve_max=10, risk_challenge_max=40, risk_critical_min=80)
    lenient = make_engine(risk_approve_max=60, risk_challenge_max=90, risk_critical_min=95)

    assert strict.decide(20) is Decision.CHALLENGE
    assert lenient.decide(20) is Decision.APPROVE
    assert strict.decide(50) is Decision.BLOCK
    assert lenient.decide(50) is Decision.APPROVE


def test_with_thresholds_does_not_mutate_original() -> None:
    """Business Cost перебирает пороги — исходный движок меняться не должен."""
    engine = RiskEngine(DEFAULT_THRESHOLDS, rules=build_rules(make_settings()))
    other = engine.with_thresholds(RiskThresholds(10, 20, 95))

    assert engine.thresholds.approve_max == 30
    assert other.thresholds.approve_max == 10
    assert other.rules == engine.rules


# ------------------------------------------------------------- правила


def test_rules_only_raise_the_score() -> None:
    """Ключевой контракт: политика не может снизить оценку модели."""
    engine = make_engine()
    high_probability = 0.95

    with_rule = engine.assess(high_probability, features(is_new_device=1.0, ip_subnet_changed=1.0))
    assert with_rule.risk_score == with_rule.model_score == 95


def test_rule_raises_low_model_score() -> None:
    engine = make_engine()
    assessment = engine.assess(0.01, features(is_new_device=1.0, ip_subnet_changed=1.0))

    assert assessment.model_score == 1
    assert assessment.risk_score == 35
    assert assessment.decision is Decision.CHALLENGE
    assert assessment.raised_by_rules
    assert [rule.key for rule in assessment.triggered_rules] == ["new_device"]


def test_disabled_rules_leave_model_score_untouched() -> None:
    engine = make_engine(rules_enabled=False)
    assessment = engine.assess(0.01, features(is_impossible_travel=1.0))

    assert assessment.risk_score == assessment.model_score == 1
    assert assessment.triggered_rules == ()
    assert not assessment.raised_by_rules


def test_highest_rule_wins_when_several_trigger() -> None:
    engine = make_engine()
    assessment = engine.assess(
        0.0,
        features(is_impossible_travel=1.0, is_new_device=1.0, ip_subnet_changed=1.0),
    )
    # impossible_travel = 75, new_device = 35 -> берётся максимум
    assert assessment.risk_score == 75
    assert len(assessment.triggered_rules) >= 2


def test_score_never_exceeds_one_hundred() -> None:
    engine = make_engine(rule_impossible_travel_min_score=100)
    assessment = engine.assess(1.0, features(is_impossible_travel=1.0))
    assert assessment.risk_score == 100


def test_rule_thresholds_are_configurable() -> None:
    engine = make_engine(rule_new_device_min_score=80)
    assessment = engine.assess(0.0, features(is_new_device=1.0, ip_subnet_changed=1.0))
    assert assessment.risk_score == 80
    assert assessment.decision is Decision.BLOCK


@pytest.mark.parametrize(
    ("key", "triggering_features"),
    [
        ("impossible_travel", {"is_impossible_travel": 1.0}),
        ("velocity_burst", {"txn_count_last_hour": 9.0}),
        ("new_account_large_amount", {"is_new_account": 1.0, "amount_deviation_ratio": 6.0}),
        ("high_risk_country", {"is_high_risk_country": 1.0}),
        ("unusual_country", {"is_unusual_country": 1.0, "ip_subnet_changed": 1.0}),
        ("new_device", {"is_new_device": 1.0, "ip_subnet_changed": 1.0}),
    ],
)
def test_each_rule_fires_on_its_own_signal(key: str, triggering_features: dict) -> None:
    rules = build_rules(make_settings())
    triggered = {rule.key for rule in evaluate_rules(rules, features(**triggering_features))}
    assert key in triggered, f"правило {key} не сработало на своём сигнале"


def test_safe_transaction_triggers_no_rules() -> None:
    rules = build_rules(make_settings())
    assert evaluate_rules(rules, features()) == ()
    assert minimum_score(()) == 0


def test_combination_rules_require_both_signals() -> None:
    """Новое устройство в своей же сети — не повод для проверки.

    Так выглядит покупка телефона, и модель оценивает такой случай низко
    совершенно справедливо. Правило должно требовать и незнакомую сеть.
    """
    rules = build_rules(make_settings())

    device_only = {rule.key for rule in evaluate_rules(rules, features(is_new_device=1.0))}
    assert "new_device" not in device_only

    country_only = {rule.key for rule in evaluate_rules(rules, features(is_unusual_country=1.0))}
    assert "unusual_country" not in country_only


def test_rules_are_skipped_without_features() -> None:
    engine = make_engine()
    assessment = engine.assess(0.42, features=None)
    assert assessment.risk_score == assessment.model_score == 42
    assert assessment.triggered_rules == ()


# ------------------------------------------------------------ результат


def test_assessment_serialises_completely() -> None:
    engine = make_engine()
    payload = engine.assess(0.5, features(is_impossible_travel=1.0)).to_dict()

    for key in (
        "probability", "model_score", "risk_score", "decision",
        "risk_level", "raised_by_rules", "triggered_rules", "thresholds",
    ):
        assert key in payload, f"в ответе нет поля {key}"

    assert payload["decision"] == Decision.BLOCK.value
    assert payload["triggered_rules"][0]["key"] == "impossible_travel"


def test_decision_matches_final_score_not_model_score() -> None:
    """Решение принимается по итоговой оценке, а не по выходу модели."""
    engine = make_engine()
    assessment = engine.assess(0.02, features(is_impossible_travel=1.0))

    assert assessment.model_score == 2
    assert engine.decide(assessment.model_score) is Decision.APPROVE
    assert assessment.decision is Decision.BLOCK
