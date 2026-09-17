"""Тесты XAI (ТЗ §7).

Проверяется то, что делает объяснение полезным, а не просто непадающим:

* факторов от 3 до 5 — прямое требование ТЗ;
* у каждого есть направление и величина вклада;
* при изменении входа меняется и состав факторов;
* три движка вкладов согласованы между собой;
* объяснение показывает не только модель, но и сработавшие политики.
"""

from __future__ import annotations

import pytest

from app.config.settings import Settings
from app.core.exceptions import ExplanationError
from app.features.definitions import FEATURE_NAMES
from app.ml.dataset import generate_dataset
from app.ml.pipeline import prepare_training_data, train_model
from app.risk_engine import RiskEngine, RiskThresholds
from app.schemas.enums import ImpactDirection
from app.xai import Explainer
from app.xai.contributions import (
    AblationContributions,
    LightGbmNativeContributions,
    ShapTreeContributions,
    build_contribution_engine,
    unwrap_tree_model,
)
from app.xai.explainer import MAX_FACTORS, MIN_FACTORS
from app.xai.narrator import describe, direction_of, is_negligible, summarise

SEED = 314


@pytest.fixture(scope="module")
def model():
    frame = generate_dataset(rows=8_000, users=300, fraud_rate=0.02, seed=SEED)
    features, target = prepare_training_data(frame)
    trained, _ = train_model(features, target, random_state=SEED)
    return trained


@pytest.fixture(scope="module")
def explainer(model) -> Explainer:
    return Explainer.from_model(model)


def safe_features() -> dict[str, float]:
    """Признаки спокойной транзакции — все флаги опущены."""
    values = dict.fromkeys(FEATURE_NAMES, 0.0)
    values.update({
        "amount_log": 4.6,
        "amount_deviation_ratio": 1.0,
        "amount_vs_previous_ratio": 1.0,
        "known_device_count": 2.0,
        "transaction_frequency": 3.0,
        "frequency_ratio": 1.0,
        "txn_count_last_hour": 1.0,
        "hours_since_previous": 5.0,
        "hour_of_day": 14.0,
        "account_age_days": 800.0,
    })
    return values


def risky_features() -> dict[str, float]:
    values = safe_features()
    values.update({
        "amount_log": 8.0,
        "amount_deviation_ratio": 25.0,
        "amount_zscore": 40.0,
        "is_new_device": 1.0,
        "ip_subnet_changed": 1.0,
        "is_unusual_country": 1.0,
        "is_high_risk_country": 1.0,
        "is_impossible_travel": 1.0,
        "travel_speed_kmh": 20000.0,
        "geo_distance_km": 7000.0,
        "hours_since_previous": 0.3,
        "txn_count_last_hour": 12.0,
        "frequency_ratio": 8.0,
        "is_high_frequency": 1.0,
    })
    return values


# ------------------------------------------------------------- DoD ТЗ §7


def test_factor_count_within_required_range(explainer: Explainer) -> None:
    """ТЗ §7: не менее 3 и не более 5 факторов."""
    for features in (safe_features(), risky_features()):
        explanation = explainer.explain(features)
        assert MIN_FACTORS <= len(explanation.factors) <= MAX_FACTORS


def test_factor_count_respects_configuration(model) -> None:
    explanation = Explainer.from_model(model, top_factors=3).explain(risky_features())
    assert len(explanation.factors) == 3


def test_top_factors_setting_is_clamped(model) -> None:
    """Настройка не должна выводить число факторов за границы ТЗ."""
    assert Explainer.from_model(model, top_factors=1).top_factors == MIN_FACTORS
    assert Explainer.from_model(model, top_factors=99).top_factors == MAX_FACTORS


def test_each_factor_has_direction_and_magnitude(explainer: Explainer) -> None:
    """ТЗ §7: у каждого фактора есть направление и величина вклада."""
    for factor in explainer.explain(risky_features()).factors:
        assert factor.direction in (ImpactDirection.INCREASES_RISK, ImpactDirection.DECREASES_RISK)
        assert isinstance(factor.contribution, float)
        assert factor.reason, f"{factor.feature}: пустая формулировка"
        assert factor.description, f"{factor.feature}: нет описания"
        expected = (
            ImpactDirection.INCREASES_RISK
            if factor.contribution > 0
            else ImpactDirection.DECREASES_RISK
        )
        assert factor.direction is expected


def test_changing_input_changes_explanation(explainer: Explainer) -> None:
    """ТЗ §7 и §15: состав факторов обязан меняться вслед за входом."""
    safe = explainer.explain(safe_features())
    risky = explainer.explain(risky_features())

    safe_names = [factor.feature for factor in safe.factors]
    risky_names = [factor.feature for factor in risky.factors]
    assert safe_names != risky_names


def test_risky_transaction_surfaces_its_anomalies(explainer: Explainer) -> None:
    """Объяснение должно называть именно те аномалии, которые есть на входе."""
    names = {factor.feature for factor in explainer.explain(risky_features()).factors}
    assert names & {"is_impossible_travel", "travel_speed_kmh", "is_new_device", "amount_zscore"}


# ------------------------------------------------------- политики в ответе


def test_policy_rules_appear_in_reasons(model) -> None:
    """Если оценку подняло правило, объяснение обязано это показать."""
    engine = RiskEngine.from_settings(Settings(rules_enabled=True))
    features = safe_features()
    features.update({"is_new_device": 1.0, "ip_subnet_changed": 1.0})

    assessment = engine.assess(0.01, features)
    explanation = Explainer.from_model(model).explain(features, assessment)

    assert assessment.raised_by_rules
    assert explanation.policy_reasons
    assert explanation.reasons[0] == explanation.policy_reasons[0], (
        "политики должны идти первыми в списке причин"
    )
    assert "policy rule" in explanation.summary


def test_reasons_have_no_duplicates(model) -> None:
    """Правило и признак могут дать одну и ту же фразу — дублировать её нельзя."""
    engine = RiskEngine.from_settings(Settings(rules_enabled=True))
    features = safe_features()
    features.update({"is_high_risk_country": 1.0, "is_unusual_country": 1.0, "ip_subnet_changed": 1.0})

    assessment = engine.assess(0.2, features)
    reasons = Explainer.from_model(model).explain(features, assessment).reasons

    lowered = [reason.strip().lower() for reason in reasons]
    assert len(lowered) == len(set(lowered)), f"повторы в причинах: {reasons}"


def test_summary_without_assessment_is_empty(explainer: Explainer) -> None:
    assert explainer.explain(safe_features()).summary == ""


# -------------------------------------------------------------- движки


def test_unwrap_finds_tree_model_inside_calibrated_wrapper(model) -> None:
    """SHAP умеет объяснять только дерево — обёртки надо снимать."""
    tree = unwrap_tree_model(model.estimator)
    assert tree is not None
    assert hasattr(tree, "booster_") or hasattr(tree, "_predictors")


def test_shap_and_native_agree(model) -> None:
    """SHAP и встроенный расчёт LightGBM — один алгоритм, числа обязаны совпасть."""
    tree = unwrap_tree_model(model.estimator)
    if not hasattr(tree, "booster_"):
        pytest.skip("модель обучена не LightGBM")

    features = risky_features()
    shap_values = ShapTreeContributions(tree).contributions(features).values
    native_values = LightGbmNativeContributions(tree.booster_).contributions(features).values

    for name in FEATURE_NAMES:
        assert shap_values[name] == pytest.approx(native_values[name], abs=1e-6), name


def test_ablation_explains_the_calibrated_probability(model) -> None:
    """Метод замены на эталон работает с итоговой моделью, а не с базовой."""
    engine = AblationContributions(model.estimator, model.feature_baseline)
    result = engine.contributions(risky_features())

    assert result.units == "probability"
    assert 0.0 <= result.base_value <= 1.0
    assert set(result.values) == set(FEATURE_NAMES)


def test_engines_agree_on_leading_anomaly(model) -> None:
    """Движки считают по-разному, но главную аномалию обязаны видеть одинаково."""
    tree = unwrap_tree_model(model.estimator)
    features = risky_features()

    leaders = []
    for engine in (
        ShapTreeContributions(tree),
        LightGbmNativeContributions(tree.booster_),
        AblationContributions(model.estimator, model.feature_baseline),
    ):
        top = engine.contributions(features).top(5)
        leaders.append({name for name, _ in top})

    common = set.intersection(*leaders)
    assert common, f"движки не сошлись ни на одном признаке: {leaders}"


def test_engine_selection_falls_back_without_shap(model) -> None:
    """Без SHAP объяснения остаются точными: используется расчёт LightGBM."""
    engine = build_contribution_engine(model, prefer_shap=False)
    assert engine.name in ("lightgbm_native", "ablation")


def test_contributions_cover_every_feature(explainer: Explainer, model) -> None:
    engine = build_contribution_engine(model)
    values = engine.contributions(risky_features()).values
    assert set(values) == set(FEATURE_NAMES)


# -------------------------------------------------------- устойчивость


def test_missing_feature_raises_domain_error(explainer: Explainer) -> None:
    broken = safe_features()
    del broken["is_new_device"]
    with pytest.raises(ExplanationError, match="is_new_device"):
        explainer.explain(broken)


def test_explanation_serialises_completely(model) -> None:
    engine = RiskEngine(RiskThresholds(30, 70, 90))
    features = risky_features()
    assessment = engine.assess(0.8, features)
    payload = Explainer.from_model(model).explain(features, assessment).to_dict()

    for key in ("method", "units", "base_value", "summary", "reasons", "policy_reasons", "factors"):
        assert key in payload, f"в ответе нет поля {key}"

    factor = payload["factors"][0]
    for key in ("feature", "value", "display_value", "contribution", "direction", "reason"):
        assert key in factor, f"в факторе нет поля {key}"


def test_explanation_is_deterministic(explainer: Explainer) -> None:
    features = risky_features()
    first = explainer.explain(features).to_dict()
    second = explainer.explain(features).to_dict()
    assert first == second


# -------------------------------------------------------------- narrator


def test_narrator_uses_direction_specific_wording() -> None:
    increasing = describe("is_new_device", 1.0, contribution=0.5)
    decreasing = describe("is_new_device", 0.0, contribution=-0.5)
    assert increasing == "New device detected"
    assert decreasing == "Device is already known for this user"


def test_narrator_substitutes_actual_value() -> None:
    text = describe("amount_deviation_ratio", 12.4, contribution=0.9)
    assert "12.4" in text
    assert "{value}" not in text


def test_narrator_falls_back_for_unknown_feature() -> None:
    """Рассинхронизация реестра не должна ронять объяснение."""
    assert "3.50" in describe("mystery_feature", 3.5, contribution=0.1)


def test_direction_and_negligible_helpers() -> None:
    assert direction_of(0.2) is ImpactDirection.INCREASES_RISK
    assert direction_of(-0.2) is ImpactDirection.DECREASES_RISK
    assert is_negligible(1e-9)
    assert not is_negligible(0.01)


def test_summary_mentions_both_sources() -> None:
    text = summarise(risk_score=87, decision="BLOCK", factor_count=5, rule_count=2)
    assert "87" in text and "BLOCK" in text
    assert "policy rule" in text and "model factor" in text

    only_rules = summarise(risk_score=55, decision="CHALLENGE", factor_count=0, rule_count=1)
    assert "policy rule" in only_rules
