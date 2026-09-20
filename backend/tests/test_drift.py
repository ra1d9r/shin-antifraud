"""Тесты наблюдения за сдвигом распределения.

Дрейф — молчаливая поломка: ничего не падает, метрики не портятся,
просто оценки модели перестают что-то значить. Поэтому проверяется
не «эндпоинт отвечает», а свойства меры: ноль на одинаковых данных,
рост на разошедшихся, конечность на пустых корзинах и молчание там,
где наблюдений слишком мало для вывода.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from app.features.definitions import FEATURE_NAMES, FEATURE_SPECS
from app.monitoring.drift import (
    MIN_OBSERVATIONS,
    PSI_EPSILON,
    BaselineMismatchError,
    BaselineNotFoundError,
    DriftBaseline,
    DriftMonitor,
    DriftStatus,
    FeatureBaseline,
    build_baseline,
    load_baseline,
    population_stability_index,
)


def flag_baseline(*, name: str = "is_new_device", expected=(0.5, 0.5)) -> FeatureBaseline:
    return FeatureBaseline(name=name, edges=(0.5,), expected=expected, labels=("нет", "да"))


def baseline_of(*features: FeatureBaseline) -> DriftBaseline:
    return DriftBaseline(
        generated_at="2026-09-20T12:00:00+00:00",
        model_trained_at="2026-09-17T14:03:39",
        rows=1000,
        features=features,
    )


def feed(monitor: DriftMonitor, value: float, times: int, *, name: str = "is_new_device") -> None:
    for _ in range(times):
        monitor.observe({name: value})


# --------------------------------------------------------------- сама мера


def test_identical_distributions_give_zero() -> None:
    assert population_stability_index((0.3, 0.3, 0.4), (0.3, 0.3, 0.4)) == 0.0


def test_psi_grows_with_divergence() -> None:
    mild = population_stability_index((0.5, 0.5), (0.45, 0.55))
    strong = population_stability_index((0.5, 0.5), (0.1, 0.9))

    assert 0 < mild < strong


def test_psi_is_symmetric() -> None:
    """Свойство формулы, а не совпадение: (b−a)·ln(b/a) не меняется местами.

    Полезно знать: «эталон против прода» и «прод против эталона» —
    одно и то же число, и спорить о направлении сравнения не придётся.
    """
    forward = population_stability_index((0.2, 0.8), (0.6, 0.4))
    backward = population_stability_index((0.6, 0.4), (0.2, 0.8))

    assert forward == pytest.approx(backward)


def test_empty_bin_does_not_give_infinity() -> None:
    """Корзина, куда в проде никто не попал, — обычное дело, а не деление на ноль."""
    psi = population_stability_index((0.5, 0.5), (1.0, 0.0))

    assert math.isfinite(psi)
    assert psi > 1.0  # исчезнувшая половина обязана выглядеть как крупный сдвиг


def test_mismatched_lengths_are_rejected() -> None:
    with pytest.raises(ValueError, match="разной длины"):
        population_stability_index((0.5, 0.5), (0.3, 0.3, 0.4))


# ------------------------------------------------------------ снятие эталона


@pytest.fixture
def training_frame():
    """Небольшая выборка со всеми признаками: часть непрерывных, часть флагов."""
    import numpy as np
    import pandas as pd

    rng = np.random.default_rng(0)
    rows = 2_000
    columns = {}
    for spec in FEATURE_SPECS:
        if spec.is_flag:
            columns[spec.name] = rng.integers(0, 2, rows).astype(float)
        else:
            columns[spec.name] = rng.normal(0.0, 1.0, rows)
    return pd.DataFrame(columns)


def test_baseline_covers_every_feature(training_frame) -> None:
    baseline = build_baseline(training_frame, model_trained_at="2026-09-17T14:03:39")

    assert tuple(feature.name for feature in baseline.features) == FEATURE_NAMES
    assert baseline.rows == len(training_frame)


def test_flags_get_two_bins_and_numbers_get_deciles(training_frame) -> None:
    baseline = build_baseline(training_frame, model_trained_at=None)
    by_name = {feature.name: feature for feature in baseline.features}

    assert by_name["is_new_device"].labels == ("нет", "да")
    assert len(by_name["is_new_device"].expected) == 2
    assert len(by_name["amount_log"].expected) == 10


def test_shares_sum_to_one_and_labels_match_bins(training_frame) -> None:
    baseline = build_baseline(training_frame, model_trained_at=None)

    for feature in baseline.features:
        assert sum(feature.expected) == pytest.approx(1.0, abs=1e-3)
        # Подписи рисуются рядом с долями: разъехавшись, они бы врали
        # молча — в таблице просто сдвинулся бы столбец.
        assert len(feature.labels) == len(feature.expected)


def test_duplicate_quantiles_collapse_instead_of_making_empty_bins(training_frame) -> None:
    """У счётчиков соседние децили совпадают.

    Без чистки границ получились бы корзины с нулевой ожидаемой долей,
    то есть сравнение с подставленным эпсилоном вместо честного.
    """
    frame = training_frame.copy()
    frame["txn_count_last_hour"] = [1.0] * 1_900 + [2.0] * 100

    feature = next(
        item
        for item in build_baseline(frame, model_trained_at=None).features
        if item.name == "txn_count_last_hour"
    )

    assert len(feature.expected) == 2
    assert all(share > 0 for share in feature.expected)


def test_constant_feature_is_marked_not_measurable(training_frame) -> None:
    frame = training_frame.copy()
    frame["geo_distance_km"] = 0.0

    feature = next(
        item
        for item in build_baseline(frame, model_trained_at=None).features
        if item.name == "geo_distance_km"
    )

    assert feature.measurable is False
    assert feature.labels == ("всё",)


# ------------------------------------------------------------ чтение с диска


def test_baseline_survives_a_round_trip(tmp_path: Path, training_frame) -> None:
    built = build_baseline(training_frame, model_trained_at="2026-09-17T14:03:39")
    path = tmp_path / "feature_baseline.json"
    path.write_text(json.dumps(built.to_dict(), ensure_ascii=False), encoding="utf-8")

    restored = load_baseline(path)

    assert restored.rows == built.rows
    assert restored.model_trained_at == built.model_trained_at
    assert restored.features[0].expected == built.features[0].expected


def test_missing_baseline_names_the_command(tmp_path: Path) -> None:
    with pytest.raises(BaselineNotFoundError, match=r"export_evaluation\.py"):
        load_baseline(tmp_path / "нет-такого.json")


def test_baseline_from_another_feature_set_is_refused(tmp_path: Path, training_frame) -> None:
    """Смена набора признаков делает эталон непригодным, а не подозрительным.

    Это единственное, что здесь проверяется строго: метка модели
    не проверяется вовсе, потому что эталон описывает датасет,
    а переобучение на тех же данных распределение не двигает.
    """
    built = build_baseline(training_frame, model_trained_at=None)
    payload = built.to_dict()
    payload["features"] = payload["features"][:-1]
    path = tmp_path / "stale.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(BaselineMismatchError, match="другого набора признаков"):
        load_baseline(path)


# ----------------------------------------------------------- наблюдение


def test_monitor_says_nothing_until_it_has_enough() -> None:
    """На полусотне транзакций PSI меряет случайность, а не сдвиг."""
    monitor = DriftMonitor(baseline_of(flag_baseline()))
    feed(monitor, 1.0, MIN_OBSERVATIONS - 1)

    report = monitor.report()

    assert report.enough_data is False
    assert report.status is DriftStatus.COLLECTING
    assert report.features[0].psi is None
    # Доли при этом уже видны: смотреть на распределение можно и раньше,
    # нельзя только называть число и делать вывод.
    assert report.features[0].observed == (0.0, 1.0)


def test_same_shape_as_training_is_stable() -> None:
    monitor = DriftMonitor(baseline_of(flag_baseline()))
    feed(monitor, 0.0, MIN_OBSERVATIONS)
    feed(monitor, 1.0, MIN_OBSERVATIONS)

    report = monitor.report()

    assert report.status is DriftStatus.STABLE
    assert report.features[0].psi == 0.0
    assert report.drifted == 0


def test_shifted_traffic_is_reported_as_significant() -> None:
    monitor = DriftMonitor(baseline_of(flag_baseline()))
    feed(monitor, 1.0, MIN_OBSERVATIONS)

    report = monitor.report()

    assert report.status is DriftStatus.SIGNIFICANT
    assert report.features[0].psi > 1.0
    assert report.drifted == 1


def test_worst_feature_decides_the_overall_status_and_goes_first() -> None:
    """Среднее растворило бы один уехавший признак среди двадцати семи."""
    monitor = DriftMonitor(
        baseline_of(flag_baseline(name="calm"), flag_baseline(name="shifted"))
    )
    for _ in range(MIN_OBSERVATIONS):
        monitor.observe({"calm": 0.0, "shifted": 1.0})
    for _ in range(MIN_OBSERVATIONS):
        monitor.observe({"calm": 1.0, "shifted": 1.0})

    report = monitor.report()

    assert report.status is DriftStatus.SIGNIFICANT
    assert report.features[0].name == "shifted"
    assert report.features[1].status is DriftStatus.STABLE


def test_constant_feature_is_not_called_stable() -> None:
    """Ноль по несравнимому признаку выглядел бы как измеренная стабильность."""
    constant = FeatureBaseline(name="flat", edges=(), expected=(1.0,), labels=("всё",))
    monitor = DriftMonitor(baseline_of(constant))
    feed(monitor, 7.0, MIN_OBSERVATIONS, name="flat")

    row = monitor.report().features[0]

    assert row.status is DriftStatus.NOT_MEASURABLE
    assert row.psi is None


def test_non_finite_value_is_counted_apart_from_the_bins() -> None:
    """Признак таким быть не должен — молчаливое округление скрыло бы поломку."""
    monitor = DriftMonitor(baseline_of(flag_baseline()))
    monitor.observe({"is_new_device": float("nan")})
    monitor.observe({"is_new_device": 1.0})

    report = monitor.report()

    assert report.invalid_values == 1
    assert report.observed_rows == 2
    # В корзину попала только одна: NaN не разложить по границам.
    assert report.features[0].observed == (0.0, 1.0)


def test_missing_feature_is_skipped_without_breaking_the_rest() -> None:
    monitor = DriftMonitor(baseline_of(flag_baseline(name="a"), flag_baseline(name="b")))
    monitor.observe({"a": 1.0})

    report = monitor.report()

    assert report.observed_rows == 1
    assert {row.name for row in report.features} == {"a", "b"}


def test_reset_clears_the_window() -> None:
    monitor = DriftMonitor(baseline_of(flag_baseline()))
    feed(monitor, 1.0, 10)
    monitor.reset()

    report = monitor.report()

    assert report.observed_rows == 0
    assert report.features[0].observed == (0.0, 0.0)


def test_memory_does_not_grow_with_traffic() -> None:
    """Смысл корзин в том, что наблюдения не хранятся.

    Проверяется свойство, а не размер объекта: счётчиков ровно столько,
    сколько корзин, сколько бы транзакций ни прошло.
    """
    monitor = DriftMonitor(baseline_of(flag_baseline()))
    feed(monitor, 1.0, 5_000)

    report = monitor.report()

    assert report.observed_rows == 5_000
    assert len(report.features[0].observed) == 2
    assert PSI_EPSILON > 0  # эпсилон — константа модуля, а не магия в формуле


# --------------------------------------------- выгруженный артефакт


@pytest.fixture(scope="module")
def committed_baseline():
    from app.config.settings import get_settings

    path = get_settings().feature_baseline_file
    if not path.exists():
        pytest.skip("эталон не выгружен")
    return load_baseline(path)


def test_committed_baseline_has_no_empty_bins(committed_baseline) -> None:
    """Главное свойство раскладки по корзинам.

    Пустая ожидаемая корзина означает сравнение с подставленным эпсилоном
    вместо честного: PSI по такому признаку меряет не сдвиг, а величину
    константы в коде. На реальном датасете это ловится только здесь —
    у синтетики из тестов другие повторы.
    """
    for feature in committed_baseline.features:
        if not feature.measurable:
            continue
        assert all(share > 0 for share in feature.expected), (
            f"{feature.name}: пустая корзина в эталоне {feature.expected}"
        )


def test_committed_baseline_covers_the_current_feature_set(committed_baseline) -> None:
    assert tuple(f.name for f in committed_baseline.features) == FEATURE_NAMES
    assert committed_baseline.rows > 0


# ------------------------------------------------------------ HTTP-слой


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client


def transaction(**overrides) -> dict:
    body = {
        "user_id": "user_drift",
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
    }
    body.update(overrides)
    return body


def test_endpoint_reports_collecting_before_it_has_enough(client) -> None:
    state = client.app.state.shin
    if state.drift is None:
        pytest.skip("эталон не выгружен")
    state.drift.reset()

    payload = client.get("/monitoring/drift").json()

    assert payload["status"] == "COLLECTING"
    assert payload["enough_data"] is False
    assert payload["min_observations"] == MIN_OBSERVATIONS
    assert len(payload["features"]) == len(FEATURE_NAMES)


def test_analysed_transactions_are_counted(client) -> None:
    state = client.app.state.shin
    if state.drift is None:
        pytest.skip("эталон не выгружен")
    state.drift.reset()

    client.post("/predict", json=transaction())
    client.post("/predict", json=transaction())

    assert client.get("/monitoring/drift").json()["observed_rows"] == 2


def test_what_if_mode_does_not_reach_the_monitor(client) -> None:
    """Десяток нажатий Analyze на одном сценарии сдвинул бы картину
    сильнее, чем настоящий поток."""
    state = client.app.state.shin
    if state.drift is None:
        pytest.skip("эталон не выгружен")
    state.drift.reset()

    client.post("/predict", json=transaction(persist=False))

    assert client.get("/monitoring/drift").json()["observed_rows"] == 0


def test_features_come_sorted_by_severity(client) -> None:
    state = client.app.state.shin
    if state.drift is None:
        pytest.skip("эталон не выгружен")
    state.drift.reset()

    for index in range(MIN_OBSERVATIONS):
        client.post("/predict", json=transaction(user_id=f"u{index}", persist=True))

    payload = client.get("/monitoring/drift").json()
    measured = [row["psi"] for row in payload["features"] if row["psi"] is not None]

    assert payload["enough_data"] is True
    assert measured == sorted(measured, reverse=True)
    # Один и тот же вход двести раз — это заведомо не обучающее
    # распределение, и наблюдение обязано это заметить.
    assert payload["status"] == "SIGNIFICANT"
    assert payload["drifted"] > 0
    state.drift.reset()


def test_without_baseline_the_endpoint_names_the_command(tmp_path) -> None:
    from fastapi.testclient import TestClient

    from app.config.settings import Settings
    from app.main import create_app

    settings = Settings(feature_baseline_path=str(tmp_path / "нет.json"))
    with TestClient(create_app(settings)) as degraded:
        response = degraded.get("/monitoring/drift")
        # Остальная система при этом работает: наблюдение необязательно.
        assert degraded.post("/predict", json=transaction()).status_code == 200

    assert response.status_code == 503
    assert response.json()["error_code"] == "baseline_not_found"
    assert "export_evaluation" in response.json()["message"]


def test_broken_baseline_does_not_stop_the_application(tmp_path) -> None:
    from fastapi.testclient import TestClient

    from app.config.settings import Settings
    from app.main import create_app

    broken = tmp_path / "broken.json"
    broken.write_text("{это не json", encoding="utf-8")

    with TestClient(create_app(Settings(feature_baseline_path=str(broken)))) as degraded:
        assert degraded.get("/health").json()["status"] == "ok"
        assert degraded.get("/monitoring/drift").status_code == 503
