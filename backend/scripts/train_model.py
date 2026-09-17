"""Обучение модели детекции фрода (ТЗ §5.3–5.5).

Запуск:
    python backend/scripts/train_model.py

Полезные флаги:
    --algorithm hist_gradient_boosting   принудительно выбрать реализацию
    --calibration sigmoid|isotonic|none  метод калибровки вероятностей
    --dataset path/to.csv                другой датасет
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import pandas as pd  # noqa: E402

from app.config.settings import get_settings  # noqa: E402
from app.core.console import enable_utf8_output  # noqa: E402
from app.core.exceptions import DatasetNotFoundError  # noqa: E402
from app.core.logging import configure_logging, get_logger  # noqa: E402
from app.features.definitions import FEATURE_NAMES  # noqa: E402
from app.ml.metrics import calibration_table, evaluate, format_metrics_report  # noqa: E402
from app.ml.pipeline import (  # noqa: E402
    load_model,
    prepare_training_data,
    save_model,
    train_model,
)

enable_utf8_output()
logger = get_logger("shin.train")

DATE_COLUMNS = ["timestamp", "previous_timestamp"]


def parse_args() -> argparse.Namespace:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Обучение модели Shin")
    parser.add_argument("--dataset", type=str, default=None, help="путь к CSV с транзакциями")
    parser.add_argument("--output", type=str, default=None, help="куда сохранить модель")
    parser.add_argument("--test-size", type=float, default=settings.test_size, help="доля теста")
    parser.add_argument("--seed", type=int, default=settings.random_seed, help="зерно")
    parser.add_argument(
        "--algorithm",
        type=str,
        default=None,
        choices=["lightgbm", "hist_gradient_boosting", "gradient_boosting"],
        help="принудительный выбор алгоритма (по умолчанию — лучший доступный)",
    )
    parser.add_argument(
        "--calibration",
        type=str,
        default="sigmoid",
        choices=["sigmoid", "isotonic", "none"],
        help="метод калибровки вероятностей (по умолчанию sigmoid — см. docstring pipeline)",
    )
    return parser.parse_args()


def load_dataset(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise DatasetNotFoundError(
            f"Датасет не найден: {path}. "
            "Сначала выполните: python backend/scripts/generate_dataset.py"
        )
    logger.info("Чтение датасета: %s", path)
    return pd.read_csv(path, parse_dates=DATE_COLUMNS)


def print_feature_importance(model, x_test, y_test, limit: int = 12) -> None:
    """Важность признаков — через permutation importance по PR-AUC.

    Работает одинаково для любой реализации бустинга и для калиброванной
    обёртки, у которой собственного `feature_importances_` нет.
    """
    from sklearn.inspection import permutation_importance
    from sklearn.metrics import average_precision_score, make_scorer

    scorer = make_scorer(average_precision_score, response_method="predict_proba")
    sample_size = min(6_000, len(x_test))
    subset = x_test.iloc[:sample_size]
    subset_target = y_test[:sample_size]

    result = permutation_importance(
        model.estimator, subset, subset_target,
        scoring=scorer, n_repeats=3, random_state=0, n_jobs=1,
    )

    ranking = sorted(
        zip(FEATURE_NAMES, result.importances_mean, strict=True),
        key=lambda item: item[1],
        reverse=True,
    )

    print("\n  Важность признаков (падение PR-AUC при перемешивании):")
    for name, importance in ranking[:limit]:
        bar = "#" * max(0, int(importance * 200))
        print(f"    {name:<30} {importance:+.4f}  {bar}")


def main() -> int:
    args = parse_args()
    settings = get_settings()
    configure_logging(settings.log_level)

    dataset_path = Path(args.dataset).resolve() if args.dataset else settings.dataset_file
    model_path = Path(args.output).resolve() if args.output else settings.model_file

    try:
        frame = load_dataset(dataset_path)
    except DatasetNotFoundError as exc:
        logger.error("%s", exc.message)
        return 1

    started = time.perf_counter()

    try:
        features, target = prepare_training_data(frame)
    except ValueError as exc:
        logger.error("Подготовка данных не удалась: %s", exc)
        return 1

    model, splits = train_model(
        features,
        target,
        test_size=args.test_size,
        random_state=args.seed,
        algorithm=args.algorithm,
        calibration=args.calibration,
    )

    elapsed = time.perf_counter() - started

    # ------------------------------------------------------------ метрики
    x_test, y_test = splits["test"]
    probabilities = model.predict_proba(x_test)
    metrics = evaluate(y_test, probabilities)
    calibration = calibration_table(y_test, probabilities)

    model.metrics = metrics.to_dict()

    # ------------------------------------------------------------ сохранение
    save_model(model, model_path)

    metrics_payload = {
        "algorithm": model.algorithm,
        "calibrated": model.calibrated,
        "calibration_method": model.calibration_method,
        "trained_at": model.trained_at,
        "training_rows": model.training_rows,
        "test_rows": int(len(y_test)),
        "feature_count": len(FEATURE_NAMES),
        "features": list(FEATURE_NAMES),
        "training_seconds": round(elapsed, 1),
        "metrics": metrics.to_dict(),
        "calibration": calibration,
    }
    metrics_path = Path(args.output).with_name("model_metrics.json") if args.output else settings.metrics_file
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    metrics_path.write_text(json.dumps(metrics_payload, indent=2, ensure_ascii=False), encoding="utf-8")

    # ------------------------------------------------------------ отчёт
    print()
    print("=" * 72)
    print("  Модель обучена")
    print("=" * 72)
    print(f"  алгоритм          : {model.algorithm}")
    print(f"  калибровка        : {model.calibration_method}")
    print(f"  признаков         : {len(FEATURE_NAMES)}")
    print(f"  время обучения    : {elapsed:.1f} с")
    print(f"  модель            : {model_path}")
    print(f"  метрики           : {metrics_path}")
    print()
    print("  Качество на тестовой выборке:")
    print(format_metrics_report(metrics))

    print()
    print("  Калибровка (среди транзакций с таким Risk Score фрода должно быть столько же):")
    print(f"    {'Risk Score':<14}{'транзакций':>12}{'предсказано':>14}{'фактически':>13}")
    for bucket in calibration:
        print(
            f"    {bucket['risk_score_range']:<14}{bucket['count']:>12}"
            f"{bucket['predicted_mean']:>14.3f}{bucket['actual_fraud_rate']:>13.3f}"
        )

    try:
        print_feature_importance(model, x_test, y_test)
    except Exception as exc:  # noqa: BLE001 — важность признаков не критична
        logger.warning("Не удалось посчитать важность признаков: %s", exc)

    # ------------------------------------------------- проверка сохранения
    reloaded = load_model(model_path)
    control = reloaded.predict_proba(x_test.head(5))
    original = probabilities[:5]
    identical = all(abs(a - b) < 1e-12 for a, b in zip(control, original, strict=True))
    print()
    print(f"  Проверка загрузки : модель читается с диска, предсказания совпадают: "
          f"{'да' if identical else 'НЕТ'}")
    print("=" * 72)

    if not identical:
        logger.error("Сохранённая модель предсказывает иначе — артефакт непригоден")
        return 1

    if metrics.roc_auc < 0.7:
        logger.error("ROC-AUC %.3f слишком низкий — обучение нельзя считать успешным", metrics.roc_auc)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
