"""ML pipeline: препроцессинг, обучение, сохранение модели (ТЗ §5).

Три решения, которые стоит понимать при чтении кода.

**1. Выбор алгоритма.**
LightGBM предпочтителен по ТЗ, но его бинарные колёса есть не под каждую
версию Python. Автоматически выбирается `LightGBM`, а при его отсутствии —
`HistGradientBoosting` из scikit-learn, который доступен всегда.
Третья реализация, `GradientBoosting`, доступна явным флагом `--algorithm`.
Обучение проходит в любом случае, меняется лишь реализация бустинга.

**2. Дисбаланс классов учитывается весами, а не «выбрасыванием» данных.**
Фрода ~2 %; undersampling выкинул бы 98 % полезной информации.
Положительный класс получает вес `scale_pos_weight` (корень из отношения
классов — см. `compute_scale_pos_weight`).

**3. После обучения вероятности калибруются — методом sigmoid.**
Это не украшение. Risk Score считается как `probability * 100`, а взвешивание
классов систематически завышает вероятности: без калибровки обычная покупка
получала бы Risk Score 40-50 и попадала в CHALLENGE.
Метод именно `sigmoid`, а не `isotonic`: причина подробно описана
в докстринге `_calibrate`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import joblib
import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.model_selection import train_test_split

from app.core.logging import get_logger
from app.features.builder import build_feature_frame
from app.features.definitions import FEATURE_NAMES

logger = get_logger("shin.ml.pipeline")

MODEL_FORMAT_VERSION = "1.1"
TARGET_COLUMN = "is_fraud"

Algorithm = Literal["lightgbm", "hist_gradient_boosting", "gradient_boosting"]
CalibrationMethod = Literal["isotonic", "sigmoid", "none"]


@dataclass(slots=True)
class TrainedModel:
    """Артефакт обучения: модель плюс всё, что нужно для честного инференса."""

    estimator: Any
    feature_names: tuple[str, ...]
    algorithm: str
    trained_at: str
    format_version: str
    metrics: dict
    calibrated: bool
    calibration_method: str
    training_rows: int
    # Медианы признаков по ЛЕГАЛЬНЫМ транзакциям обучающей выборки.
    # Это эталон «типичной безопасной операции»: XAI-модуль сравнивает
    # с ним текущую транзакцию, когда SHAP недоступен.
    feature_baseline: dict[str, float] = field(default_factory=dict)

    def predict_proba(self, features: dict[str, float] | pd.DataFrame) -> np.ndarray:
        """Вероятность фрода.

        Принимает либо словарь признаков одной транзакции, либо готовый
        DataFrame. Порядок колонок восстанавливается из `feature_names`,
        поэтому перепутать его невозможно.
        """
        if isinstance(features, dict):
            frame = pd.DataFrame([[features[name] for name in self.feature_names]],
                                 columns=list(self.feature_names))
        else:
            frame = features[list(self.feature_names)]

        return self.estimator.predict_proba(frame)[:, 1]

    def predict_one(self, features: dict[str, float]) -> float:
        """Вероятность фрода для одной транзакции."""
        return float(self.predict_proba(features)[0])


def detect_algorithm() -> Algorithm:
    """Какой бустинг доступен в этом окружении."""
    try:
        import lightgbm  # noqa: F401

        return "lightgbm"
    except ImportError:
        logger.warning("LightGBM недоступен — используется scikit-learn")
        return "hist_gradient_boosting"


def build_estimator(
    algorithm: Algorithm,
    scale_pos_weight: float,
    random_state: int = 42,
) -> Any:
    """Создать необученную модель выбранного типа."""
    if algorithm == "lightgbm":
        from lightgbm import LGBMClassifier

        return LGBMClassifier(
            n_estimators=400,
            learning_rate=0.05,
            num_leaves=31,
            max_depth=-1,
            min_child_samples=40,
            subsample=0.9,
            subsample_freq=1,
            colsample_bytree=0.9,
            reg_lambda=1.0,
            scale_pos_weight=scale_pos_weight,
            random_state=random_state,
            n_jobs=-1,
            verbose=-1,
        )

    if algorithm == "hist_gradient_boosting":
        from sklearn.ensemble import HistGradientBoostingClassifier

        return HistGradientBoostingClassifier(
            max_iter=400,
            learning_rate=0.05,
            max_leaf_nodes=31,
            min_samples_leaf=40,
            l2_regularization=1.0,
            class_weight={0: 1.0, 1: scale_pos_weight},
            random_state=random_state,
        )

    from sklearn.ensemble import GradientBoostingClassifier

    # У GradientBoosting нет class_weight — вес задаётся через sample_weight
    # при вызове fit (см. `_fit_estimator`).
    return GradientBoostingClassifier(
        n_estimators=200,
        learning_rate=0.05,
        max_depth=4,
        min_samples_leaf=40,
        random_state=random_state,
    )


def _fit_estimator(
    estimator: Any,
    algorithm: Algorithm,
    x_train: pd.DataFrame,
    y_train: np.ndarray,
    scale_pos_weight: float,
) -> Any:
    """Обучить модель, передав веса классов тем способом, который она понимает."""
    if algorithm == "gradient_boosting":
        sample_weight = np.where(y_train == 1, scale_pos_weight, 1.0)
        estimator.fit(x_train, y_train, sample_weight=sample_weight)
    else:
        estimator.fit(x_train, y_train)
    return estimator


def _calibrate(
    estimator: Any,
    x_calibration: pd.DataFrame,
    y_calibration: np.ndarray,
    method: CalibrationMethod = "sigmoid",
) -> Any:
    """Калибровка вероятностей на отложенной части выборки.

    Метод по умолчанию — `sigmoid` (Платт), а не `isotonic`, и это осознанный
    выбор под задачу. Изотоническая регрессия — кусочно-постоянная функция:
    на хорошо разделимой задаче она отображает почти все входы ровно в 0.0
    или 1.0. Формально калибровка при этом отличная (Brier низкий), но
    Risk Score превращается в двоичный «0 или 100», промежуточные решения
    становятся недостижимыми, и требование ТЗ §9 о постепенном росте риска
    выполнить нельзя. Сигмоида даёт гладкую шкалу и не упирается в границы.
    """
    try:
        from sklearn.frozen import FrozenEstimator

        calibrator = CalibratedClassifierCV(FrozenEstimator(estimator), method=method)
    except ImportError:  # sklearn < 1.6
        calibrator = CalibratedClassifierCV(estimator, method=method, cv="prefit")

    calibrator.fit(x_calibration, y_calibration)
    return calibrator


def compute_scale_pos_weight(y: np.ndarray, strategy: str = "sqrt") -> float:
    """Вес положительного класса.

    Полное выравнивание (`neg / pos`, около 50x) сильно смещает вероятности
    и ухудшает калибровку. Корень из этого отношения — компромисс: модель
    обращает достаточно внимания на редкий класс, но распределение
    вероятностей остаётся вменяемым, а остаток смещения снимает калибровка.
    """
    positives = float((y == 1).sum())
    negatives = float((y == 0).sum())
    if positives == 0:
        return 1.0

    ratio = negatives / positives
    if strategy == "full":
        return ratio
    if strategy == "none":
        return 1.0
    return math.sqrt(ratio)


def prepare_training_data(frame: pd.DataFrame) -> tuple[pd.DataFrame, np.ndarray]:
    """Сырой датасет -> матрица признаков и целевая переменная.

    Признаки считает тот же модуль, что работает в API, — это гарантия
    отсутствия training/serving skew.
    """
    if TARGET_COLUMN not in frame.columns:
        raise ValueError(f"В датасете нет целевой колонки '{TARGET_COLUMN}'")

    logger.info("Построение признаков для %s строк...", f"{len(frame):,}".replace(",", " "))
    features = build_feature_frame(frame)
    target = frame[TARGET_COLUMN].to_numpy().astype(int)

    if features.isna().to_numpy().any():
        raise ValueError("В матрице признаков есть NaN — обучение остановлено")

    return features, target


def split_dataset(
    features: pd.DataFrame,
    target: np.ndarray,
    test_size: float = 0.2,
    calibration_size: float = 0.2,
    random_state: int = 42,
) -> dict[str, tuple[pd.DataFrame, np.ndarray]]:
    """Стратифицированное разбиение train / calibration / test.

    Калибровка обязана происходить на данных, которых модель не видела при
    обучении, иначе она подгонит вероятности под собственные ошибки.
    """
    x_pool, x_test, y_pool, y_test = train_test_split(
        features, target, test_size=test_size, stratify=target, random_state=random_state
    )

    relative_calibration = calibration_size / (1.0 - test_size)
    x_train, x_calibration, y_train, y_calibration = train_test_split(
        x_pool, y_pool, test_size=relative_calibration, stratify=y_pool, random_state=random_state
    )

    return {
        "train": (x_train, y_train),
        "calibration": (x_calibration, y_calibration),
        "test": (x_test, y_test),
    }


def train_model(
    features: pd.DataFrame,
    target: np.ndarray,
    *,
    test_size: float = 0.2,
    random_state: int = 42,
    algorithm: Algorithm | None = None,
    calibration: CalibrationMethod = "sigmoid",
) -> tuple[TrainedModel, dict[str, tuple[pd.DataFrame, np.ndarray]]]:
    """Обучить модель. Возвращает артефакт и разбиение (для отчёта о метриках)."""
    chosen = algorithm or detect_algorithm()
    splits = split_dataset(features, target, test_size=test_size, random_state=random_state)

    x_train, y_train = splits["train"]
    x_calibration, y_calibration = splits["calibration"]

    scale_pos_weight = compute_scale_pos_weight(y_train)
    logger.info(
        "Алгоритм: %s | train=%s, calibration=%s, test=%s | scale_pos_weight=%.2f",
        chosen,
        f"{len(x_train):,}".replace(",", " "),
        f"{len(x_calibration):,}".replace(",", " "),
        f"{len(splits['test'][0]):,}".replace(",", " "),
        scale_pos_weight,
    )

    estimator = build_estimator(chosen, scale_pos_weight, random_state=random_state)
    estimator = _fit_estimator(estimator, chosen, x_train, y_train, scale_pos_weight)

    # Эталон безопасной транзакции: медианы признаков по легальным строкам.
    baseline = x_train[y_train == 0].median().to_dict()

    final_estimator = estimator
    if calibration != "none":
        logger.info("Калибровка вероятностей (%s) на отложенной выборке...", calibration)
        final_estimator = _calibrate(estimator, x_calibration, y_calibration, method=calibration)

    model = TrainedModel(
        estimator=final_estimator,
        feature_names=tuple(FEATURE_NAMES),
        algorithm=chosen,
        trained_at=datetime.now().isoformat(timespec="seconds"),
        format_version=MODEL_FORMAT_VERSION,
        metrics={},
        calibrated=calibration != "none",
        calibration_method=calibration,
        training_rows=len(x_train),
        feature_baseline={name: float(value) for name, value in baseline.items()},
    )
    return model, splits


def save_model(model: TrainedModel, path: Path) -> None:
    """Сохранить артефакт модели на диск."""
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, path)
    logger.info("Модель сохранена: %s (%.1f MB)", path, path.stat().st_size / 1024 / 1024)


def load_model(path: Path) -> TrainedModel:
    """Загрузить артефакт модели с диска."""
    model = joblib.load(path)
    if not isinstance(model, TrainedModel):
        raise TypeError(f"Файл {path} не содержит модель Shin")
    if tuple(model.feature_names) != tuple(FEATURE_NAMES):
        raise ValueError(
            "Набор признаков модели не совпадает с текущим реестром — "
            "нужно переобучение (python backend/scripts/train_model.py)"
        )
    return model
