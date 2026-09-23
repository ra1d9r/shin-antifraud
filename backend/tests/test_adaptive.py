"""Тесты адаптивного порога по категории мерчанта (брифинг §6).

Проверяется три вещи, и в таком порядке по важности.

Во-первых, режим не должен ломать систему ни на одном входе: порог
сегмента может оказаться выше действующей границы проверки, сегмент
может быть незнакомым, его может не быть вовсе. Раньше первый из этих
случаев уронил бы запрос пятисоткой.

Во-вторых, подбор должен быть подбором, а не назначением: порог обязан
минимизировать ту же функцию стоимости, что и остальной проект.

В-третьих, проверка выигрыша обязана быть честной — на данных, которых
подбор не видел.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.config.settings import Settings
from app.main import create_app
from app.risk_engine.adaptive import (
    AdaptiveThresholds,
    AdaptiveThresholdsNotFoundError,
    SegmentThreshold,
    best_threshold,
    fit,
    load,
    save,
    validate,
)
from app.risk_engine.engine import RiskEngine, RiskThresholds

SETTINGS = Settings()
BASE = RiskThresholds(approve_max=30, challenge_max=70, critical_min=90)


def table(segments: dict[str, int], fallback: int = 5) -> AdaptiveThresholds:
    return AdaptiveThresholds(
        fallback_approve_max=fallback,
        segments=tuple(
            SegmentThreshold(segment=key, approve_max=value, rows=1000, fraud_rows=50, fitted=True)
            for key, value in segments.items()
        ),
        generated_at="2026-09-21T00:00:00+00:00",
        rows=99360,
        min_fraud_per_segment=30,
    )


# ------------------------------------------------- устойчивость к входу


def test_threshold_above_the_challenge_border_does_not_break_the_request() -> None:
    """Подобранный порог может оказаться выше границы проверки.

    Так бывает, если оператор опустил `challenge_max` в рантайме.
    `RiskThresholds` с approve_max >= challenge_max не собирается вовсе,
    и без прижатия запрос падал бы пятисоткой из-за настройки
    чувствительности — то есть из-за улучшения, которое должно было
    только уменьшить трение.
    """
    engine = RiskEngine(BASE, adaptive=table({"electronics": 95}))

    thresholds, segment = engine.thresholds_for("electronics")

    assert thresholds.approve_max == BASE.challenge_max - 1
    assert segment == "electronics"


def test_operator_lowered_the_border_below_every_fitted_threshold() -> None:
    tight = RiskThresholds(approve_max=10, challenge_max=20, critical_min=50)
    engine = RiskEngine(tight, adaptive=table({"atm": 55}))

    thresholds, _ = engine.thresholds_for("atm")

    assert thresholds.approve_max == 19
    assert thresholds.challenge_max == 20


@pytest.mark.parametrize("segment", [None, "unknown", "категории-нет-в-таблице"])
def test_unknown_segment_falls_back_to_the_shared_threshold(segment) -> None:
    """Незнакомая категория — не ошибка: мерчанта может не быть в справочнике."""
    engine = RiskEngine(BASE, adaptive=table({"grocery": 11}))

    thresholds, applied = engine.thresholds_for(segment)

    assert thresholds.approve_max == 5
    assert applied is None, "нельзя называть сегмент, порог которого не применяли"


def test_disabled_mode_changes_nothing() -> None:
    """Без подобранных порогов движок обязан вести себя ровно как прежде."""
    engine = RiskEngine(BASE)

    thresholds, applied = engine.thresholds_for("grocery")

    assert thresholds is BASE
    assert applied is None


def test_the_segment_actually_changes_the_decision() -> None:
    """Смысл режима: одна и та же оценка решается по-разному."""
    engine = RiskEngine(BASE, adaptive=table({"gaming": 3, "electronics": 61}))

    strict = engine.assess(0.30, {}, segment="gaming")
    lenient = engine.assess(0.30, {}, segment="electronics")

    assert strict.risk_score == lenient.risk_score == 30
    assert strict.decision.value == "CHALLENGE"
    assert lenient.decision.value == "APPROVE"
    assert strict.segment == "gaming"


# ---------------------------------------------------------- сам подбор


def test_fitted_threshold_is_the_cheapest_one() -> None:
    """Порог обязан быть минимумом функции стоимости, а не выбранным на глаз."""
    scores = [10, 20, 30, 40, 50, 60, 70, 80]
    labels = [False, False, False, False, True, True, True, True]
    amounts = [100.0] * 8

    fitted = fit(scores, labels, amounts, ["one"] * 8, settings=SETTINGS)
    chosen = fitted.segments[0].approve_max

    fraud_costs = [
        a * SETTINGS.cost_fraud_loss_ratio + SETTINGS.cost_fraud_fixed for a in amounts
    ]
    assert chosen == best_threshold(scores, labels, fraud_costs, SETTINGS)


def test_a_segment_without_enough_fraud_takes_the_shared_threshold() -> None:
    """На десятке случаев минимум определяется одной крупной операцией.

    Такой «подбор» — это шум, выданный за настройку, поэтому сегмент
    честно помечается неподобранным.
    """
    scores = [5, 95] * 40
    labels = [False, True] * 40
    amounts = [100.0] * 80
    segments = ["big"] * 70 + ["tiny"] * 10

    fitted = fit(scores, labels, amounts, segments, settings=SETTINGS, min_fraud=30)
    by_name = {item.segment: item for item in fitted.segments}

    assert by_name["tiny"].fitted is False
    assert by_name["tiny"].approve_max == fitted.fallback_approve_max
    assert by_name["big"].fitted is True


def test_ties_are_broken_towards_the_stricter_threshold() -> None:
    """Между двумя одинаково дешёвыми настройками антифрод берёт строгую."""
    # Ни одной операции: любой порог стоит ноль.
    assert best_threshold([], [], [], SETTINGS) == 0


def test_every_segment_of_the_input_appears_in_the_table() -> None:
    scores = [10, 20, 30, 40]
    labels = [False, True, False, True]
    amounts = [100.0] * 4

    fitted = fit(scores, labels, amounts, ["a", "b", "a", "c"], settings=SETTINGS)

    assert set(fitted.segment_names()) == {"a", "b", "c"}
    assert sum(item.rows for item in fitted.segments) == 4


# ------------------------------------------------------------- проверка


def test_validation_measures_on_rows_it_did_not_fit_on() -> None:
    """Иначе выигрыш был бы подгонкой под ответ.

    Проверяется косвенно, но надёжно: на чистом шуме, где сегмент
    не несёт никакой информации, честная перекрёстная проверка не может
    выигрывать во всех частях. Подбор и проверка на одних данных —
    могли бы.
    """
    rng_scores = [(i * 37) % 101 for i in range(600)]
    labels = [i % 7 == 0 for i in range(600)]
    amounts = [100.0] * 600
    segments = [f"s{i % 3}" for i in range(600)]

    result = validate(
        rng_scores,
        labels,
        amounts,
        segments,
        settings=SETTINGS,
        configured_approve_max=30,
        folds=5,
    )

    assert result.folds == 5
    assert len(result.gain_per_fold) == 5
    assert result.positive_folds < 5, "на бессмысленных сегментах выигрыша быть не должно везде"


def test_validation_reports_both_comparisons() -> None:
    """Два вопроса — два ответа: даёт ли сегментация что-то сверх одного
    подобранного порога, и что изменится на действующей настройке."""
    scores = [i % 101 for i in range(500)]
    labels = [i % 11 == 0 for i in range(500)]
    amounts = [100.0] * 500
    segments = ["low" if s < 50 else "high" for s in scores]

    result = validate(
        scores, labels, amounts, segments,
        settings=SETTINGS, configured_approve_max=30, folds=5,
    )

    assert result.configured_approve_max == 30
    assert result.configured_cost >= 0
    assert result.adaptive_cost >= 0
    assert result.mean_gain == pytest.approx(sum(result.gain_per_fold) / 5)
    assert result.worst_gain == min(result.gain_per_fold)


# ------------------------------------------------------------- артефакт


def test_artifact_survives_a_round_trip(tmp_path) -> None:
    scores = [10, 20, 30, 40, 50, 60]
    labels = [False, False, True, False, True, True]
    amounts = [100.0] * 6
    validation = validate(
        scores, labels, amounts, ["a"] * 6,
        settings=SETTINGS, configured_approve_max=30, folds=3,
    )
    original = fit(scores, labels, amounts, ["a"] * 6, settings=SETTINGS, validation=validation)

    path = tmp_path / "adaptive.json"
    save(original, path)
    restored = load(path)

    assert restored.to_dict() == original.to_dict()
    assert restored.validation is not None
    assert restored.validation.gain_per_fold == pytest.approx(validation.gain_per_fold)


def test_missing_artifact_names_the_command(tmp_path) -> None:
    with pytest.raises(AdaptiveThresholdsNotFoundError) as failure:
        load(tmp_path / "nope.json")

    assert "export_evaluation.py" in failure.value.message


def test_artifact_of_another_format_is_refused(tmp_path) -> None:
    """Молча прочитать чужой формат — значит применить неизвестно что."""
    path = tmp_path / "adaptive.json"
    path.write_text(json.dumps({"format_version": "99", "segments": []}), encoding="utf-8")

    with pytest.raises(AdaptiveThresholdsNotFoundError):
        load(path)


# ---------------------------------------------------------------- HTTP


@pytest.fixture(scope="module")
def client():
    with TestClient(create_app()) as test_client:
        yield test_client


def test_endpoint_shows_the_table_and_what_it_is_worth(client) -> None:
    payload = client.get("/config/adaptive").json()

    assert payload["available"] is True, "артефакт должен быть выгружен вместе с аналитикой"
    assert payload["segments"], "таблица порогов пуста"
    assert payload["validation"] is not None, (
        "таблица без проверки — набор чисел, выданный за улучшение"
    )
    assert payload["validation"]["folds"] >= 2


def test_endpoint_tells_whether_the_mode_is_actually_on(client) -> None:
    """`enabled` описывает движок, а не настройку: пороги могли сменить
    в рантайме, и тогда настройка соврала бы."""
    payload = client.get("/config/adaptive").json()
    state = client.app.state.shin

    assert payload["enabled"] is (state.risk_engine.adaptive is not None)


def test_prediction_says_which_threshold_was_applied(client) -> None:
    """Режим, который нельзя объяснить, ничем не лучше случайного."""
    body = {
        "user_id": "adaptive_user",
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
        "persist": False,
    }

    thresholds = client.post("/predict", json=body).json()["thresholds"]

    assert "segment" in thresholds
    state = client.app.state.shin
    if state.risk_engine.adaptive is None:
        assert thresholds["segment"] is None, "выключенный режим не должен называть сегмент"
