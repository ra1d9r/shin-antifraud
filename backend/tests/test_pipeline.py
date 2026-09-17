"""Тесты ML pipeline (ТЗ §5.3–5.5).

Проверяется не только «обучение не падает», но и свойства, от которых зависит
пригодность модели: отсутствие утечки между train и calibration, сохранение
порядка признаков, работоспособность fallback-алгоритма и то, что сохранённая
модель предсказывает ровно так же, как обученная.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.features.definitions import FEATURE_NAMES
from app.ml.dataset import generate_dataset
from app.ml.metrics import calibration_table, evaluate, metrics_at_threshold
from app.ml.pipeline import (
    compute_scale_pos_weight,
    detect_algorithm,
    load_model,
    prepare_training_data,
    save_model,
    split_dataset,
    train_model,
)

# Небольшая выборка: тесты должны идти быстро, свойства проявляются и здесь.
ROWS = 12_000
USERS = 400
SEED = 77


@pytest.fixture(scope="module")
def training_data():
    frame = generate_dataset(rows=ROWS, users=USERS, fraud_rate=0.02, seed=SEED)
    return prepare_training_data(frame)


@pytest.fixture(scope="module")
def trained(training_data):
    features, target = training_data
    return train_model(features, target, random_state=SEED)


# ----------------------------------------------------------- подготовка


def test_feature_matrix_shape_and_order(training_data) -> None:
    features, target = training_data
    assert list(features.columns) == list(FEATURE_NAMES)
    assert len(features) == len(target)
    assert not features.isna().to_numpy().any()


def test_target_has_both_classes(training_data) -> None:
    _, target = training_data
    assert set(np.unique(target)) == {0, 1}


def test_missing_target_column_is_rejected() -> None:
    frame = generate_dataset(rows=1_000, users=50, seed=1).drop(columns=["is_fraud"])
    with pytest.raises(ValueError, match="is_fraud"):
        prepare_training_data(frame)


# --------------------------------------------------------- разбиение


def test_split_is_disjoint_and_stratified(training_data) -> None:
    """Калибровка обязана идти на данных, которых модель не видела."""
    features, target = training_data
    splits = split_dataset(features, target, random_state=SEED)

    train_index = set(splits["train"][0].index)
    calibration_index = set(splits["calibration"][0].index)
    test_index = set(splits["test"][0].index)

    assert not train_index & calibration_index, "train и calibration пересекаются"
    assert not train_index & test_index, "train и test пересекаются"
    assert not calibration_index & test_index, "calibration и test пересекаются"
    assert len(train_index) + len(calibration_index) + len(test_index) == len(features)

    # Доля фрода должна сохраняться в каждой части.
    overall = target.mean()
    for name, (_, part_target) in splits.items():
        assert part_target.mean() == pytest.approx(overall, abs=0.01), f"перекос в части {name}"


# ------------------------------------------------------ дисбаланс классов


def test_scale_pos_weight_accounts_for_imbalance() -> None:
    target = np.array([0] * 980 + [1] * 20)
    weight = compute_scale_pos_weight(target)
    assert weight > 1.0, "положительный класс обязан получить вес больше единицы"
    assert weight == pytest.approx(np.sqrt(980 / 20), rel=1e-6)

    assert compute_scale_pos_weight(target, strategy="full") == pytest.approx(49.0)
    assert compute_scale_pos_weight(target, strategy="none") == 1.0
    assert compute_scale_pos_weight(np.zeros(10, dtype=int)) == 1.0


# ---------------------------------------------------------- обучение


def test_model_trains_and_beats_random(trained) -> None:
    model, splits = trained
    x_test, y_test = splits["test"]
    probabilities = model.predict_proba(x_test)
    metrics = evaluate(y_test, probabilities)

    assert metrics.roc_auc > 0.85, f"ROC-AUC {metrics.roc_auc:.3f} — модель почти не учится"
    assert metrics.pr_auc > 0.5, f"PR-AUC {metrics.pr_auc:.3f} слишком низкий"
    assert metrics.default.recall > 0.4


def test_model_is_not_a_random_stub(trained) -> None:
    """ТЗ §5 прямо запрещает заглушку вместо ML: предсказания обязаны зависеть
    от входа и быть воспроизводимыми."""
    model, splits = trained
    x_test, _ = splits["test"]

    first = model.predict_proba(x_test.head(50))
    second = model.predict_proba(x_test.head(50))

    assert np.array_equal(first, second), "предсказания не воспроизводимы"
    assert first.std() > 0.01, "модель выдаёт одно и то же значение всем"


def test_model_keeps_feature_order(trained) -> None:
    model, _ = trained
    assert tuple(model.feature_names) == tuple(FEATURE_NAMES)


def test_probabilities_are_valid(trained) -> None:
    model, splits = trained
    probabilities = model.predict_proba(splits["test"][0])
    assert probabilities.min() >= 0.0
    assert probabilities.max() <= 1.0
    assert np.isfinite(probabilities).all()


def test_predict_one_accepts_feature_dict(trained) -> None:
    model, splits = trained
    x_test, _ = splits["test"]
    row = x_test.iloc[0].to_dict()

    single = model.predict_one(row)
    batch = float(model.predict_proba(x_test.head(1))[0])
    assert single == pytest.approx(batch, abs=1e-12)


def test_calibration_is_applied_by_default(trained) -> None:
    model, _ = trained
    assert model.calibrated
    assert model.calibration_method == "sigmoid"


def test_uncalibrated_model_can_be_trained(training_data) -> None:
    features, target = training_data
    model, _ = train_model(features, target, random_state=SEED, calibration="none")
    assert not model.calibrated
    assert model.calibration_method == "none"


def test_sklearn_fallback_algorithm_works(training_data) -> None:
    """Проект обязан обучаться и без LightGBM."""
    features, target = training_data
    model, splits = train_model(
        features, target, random_state=SEED, algorithm="hist_gradient_boosting"
    )
    assert model.algorithm == "hist_gradient_boosting"

    x_test, y_test = splits["test"]
    metrics = evaluate(y_test, model.predict_proba(x_test))
    assert metrics.roc_auc > 0.85


def test_detect_algorithm_returns_known_value() -> None:
    assert detect_algorithm() in {"lightgbm", "hist_gradient_boosting"}


# ------------------------------------------------- сохранение и загрузка


def test_saved_model_predicts_identically(trained, tmp_path) -> None:
    model, splits = trained
    path = tmp_path / "model.joblib"
    save_model(model, path)

    reloaded = load_model(path)
    x_test, _ = splits["test"]

    original = model.predict_proba(x_test.head(100))
    restored = reloaded.predict_proba(x_test.head(100))
    assert np.allclose(original, restored, atol=1e-12)
    assert reloaded.algorithm == model.algorithm
    assert tuple(reloaded.feature_names) == tuple(model.feature_names)


def test_load_rejects_foreign_file(tmp_path) -> None:
    import joblib

    path = tmp_path / "not_a_model.joblib"
    joblib.dump({"hello": "world"}, path)
    with pytest.raises(TypeError, match="не содержит модель"):
        load_model(path)


def test_load_rejects_model_with_stale_features(trained, tmp_path) -> None:
    """Модель со старым набором признаков должна отвергаться, а не молча врать."""
    from dataclasses import replace

    model, _ = trained
    stale = replace(model, feature_names=tuple(FEATURE_NAMES[:-1]))
    path = tmp_path / "stale.joblib"
    save_model(stale, path)

    with pytest.raises(ValueError, match="переобучение"):
        load_model(path)


# ------------------------------------------------------------- метрики


def test_metrics_report_contains_required_values(trained) -> None:
    """ТЗ §5 требует precision, recall, F1 и ROC-AUC."""
    model, splits = trained
    x_test, y_test = splits["test"]
    payload = evaluate(y_test, model.predict_proba(x_test)).to_dict()

    for key in ("precision", "recall", "f1", "roc_auc", "pr_auc", "confusion_matrix"):
        assert key in payload, f"в метриках нет {key}"


def test_metrics_at_threshold_matches_confusion_matrix() -> None:
    y_true = np.array([0, 0, 1, 1, 0, 1])
    probabilities = np.array([0.1, 0.2, 0.9, 0.8, 0.7, 0.3])

    result = metrics_at_threshold(y_true, probabilities, 0.5)
    assert result.true_positives == 2
    assert result.false_positives == 1
    assert result.false_negatives == 1
    assert result.true_negatives == 2
    assert result.precision == pytest.approx(2 / 3)
    assert result.recall == pytest.approx(2 / 3)


def test_evaluate_rejects_single_class() -> None:
    with pytest.raises(ValueError, match="один класс"):
        evaluate(np.zeros(10, dtype=int), np.linspace(0, 1, 10))


def test_calibration_table_is_meaningful(trained) -> None:
    """Калибровка: среди транзакций со счётом ~X фрода должно быть около X %."""
    model, splits = trained
    x_test, y_test = splits["test"]
    table = calibration_table(y_test, model.predict_proba(x_test))

    assert table, "таблица калибровки пуста"
    assert sum(bucket["count"] for bucket in table) == len(y_test)

    # В самом нижнем ведре фрода почти не должно быть.
    lowest = table[0]
    assert lowest["actual_fraud_rate"] < 0.1


def test_scores_spread_across_the_scale(trained) -> None:
    """Risk Score не должен вырождаться в «0 или 100».

    Именно это происходило при изотонической калибровке и делало полосу
    CHALLENGE недостижимой (см. docs/TZ.md, отклонение D-7).
    """
    model, splits = trained
    x_test, _ = splits["test"]
    scores = np.round(model.predict_proba(x_test) * 100)

    middle = int(((scores > 10) & (scores < 90)).sum())
    assert middle > 0, "ни одна транзакция не попала в середину шкалы риска"
