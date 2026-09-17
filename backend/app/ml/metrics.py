"""Метрики качества модели (ТЗ §5).

Помимо обязательных precision / recall / F1 / ROC-AUC считаются:

* **PR-AUC** — при доле положительного класса ~2 % именно он честно показывает
  качество; ROC-AUC на сильном дисбалансе выглядит оптимистично;
* **Brier score** — качество *калибровки* вероятностей. Для Shin это не
  академическая метрика: Risk Score считается как `probability * 100`,
  поэтому плохо откалиброванная модель ломает пороги решений;
* **метрики на рабочих порогах** Risk Score, а не только на условных 0.5.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)


@dataclass(slots=True)
class ThresholdMetrics:
    """Метрики на одном пороге вероятности."""

    threshold: float
    precision: float
    recall: float
    f1: float
    true_positives: int
    false_positives: int
    true_negatives: int
    false_negatives: int

    def to_dict(self) -> dict:
        return {
            "threshold": round(self.threshold, 4),
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1": round(self.f1, 4),
            "true_positives": self.true_positives,
            "false_positives": self.false_positives,
            "true_negatives": self.true_negatives,
            "false_negatives": self.false_negatives,
        }


@dataclass(slots=True)
class ModelMetrics:
    """Полный отчёт о качестве модели."""

    roc_auc: float
    pr_auc: float
    brier_score: float
    positive_rate: float
    samples: int
    default: ThresholdMetrics
    best_f1: ThresholdMetrics
    by_threshold: list[ThresholdMetrics] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "roc_auc": round(self.roc_auc, 4),
            "pr_auc": round(self.pr_auc, 4),
            "brier_score": round(self.brier_score, 6),
            "positive_rate": round(self.positive_rate, 5),
            "samples": self.samples,
            # Обязательные метрики ТЗ §5 — на пороге 0.5
            "precision": round(self.default.precision, 4),
            "recall": round(self.default.recall, 4),
            "f1": round(self.default.f1, 4),
            "confusion_matrix": {
                "true_positives": self.default.true_positives,
                "false_positives": self.default.false_positives,
                "true_negatives": self.default.true_negatives,
                "false_negatives": self.default.false_negatives,
            },
            "best_f1": self.best_f1.to_dict(),
            "by_threshold": [item.to_dict() for item in self.by_threshold],
        }


def metrics_at_threshold(
    y_true: np.ndarray,
    probabilities: np.ndarray,
    threshold: float,
) -> ThresholdMetrics:
    """Precision / recall / F1 и матрица ошибок на заданном пороге."""
    predictions = (probabilities >= threshold).astype(int)
    matrix = confusion_matrix(y_true, predictions, labels=[0, 1])
    true_negatives, false_positives, false_negatives, true_positives = matrix.ravel()

    return ThresholdMetrics(
        threshold=float(threshold),
        precision=float(precision_score(y_true, predictions, zero_division=0)),
        recall=float(recall_score(y_true, predictions, zero_division=0)),
        f1=float(f1_score(y_true, predictions, zero_division=0)),
        true_positives=int(true_positives),
        false_positives=int(false_positives),
        true_negatives=int(true_negatives),
        false_negatives=int(false_negatives),
    )


def evaluate(
    y_true: np.ndarray,
    probabilities: np.ndarray,
    thresholds: tuple[float, ...] = (0.05, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9),
) -> ModelMetrics:
    """Посчитать полный отчёт о качестве модели."""
    y_true = np.asarray(y_true).astype(int)
    probabilities = np.asarray(probabilities, dtype=float)

    if y_true.shape != probabilities.shape:
        raise ValueError("Размерности y_true и probabilities не совпадают")
    if len(np.unique(y_true)) < 2:
        raise ValueError("В выборке представлен только один класс — метрики не определены")

    by_threshold = [metrics_at_threshold(y_true, probabilities, t) for t in thresholds]
    best = max(by_threshold, key=lambda item: item.f1)

    return ModelMetrics(
        roc_auc=float(roc_auc_score(y_true, probabilities)),
        pr_auc=float(average_precision_score(y_true, probabilities)),
        brier_score=float(brier_score_loss(y_true, probabilities)),
        positive_rate=float(y_true.mean()),
        samples=int(len(y_true)),
        default=metrics_at_threshold(y_true, probabilities, 0.5),
        best_f1=best,
        by_threshold=by_threshold,
    )


def calibration_table(
    y_true: np.ndarray,
    probabilities: np.ndarray,
    bins: int = 10,
) -> list[dict]:
    """Таблица калибровки: предсказанная вероятность против фактической доли.

    Нужна, чтобы убедиться, что Risk Score = probability * 100 честен:
    среди транзакций со счётом ~70 действительно должно быть около 70 % фрода.
    """
    y_true = np.asarray(y_true).astype(int)
    probabilities = np.asarray(probabilities, dtype=float)

    edges = np.linspace(0.0, 1.0, bins + 1)
    table: list[dict] = []

    for index in range(bins):
        low, high = edges[index], edges[index + 1]
        mask = (probabilities >= low) & (probabilities < high if index < bins - 1 else probabilities <= high)
        count = int(mask.sum())
        if count == 0:
            continue
        table.append(
            {
                "bucket": f"{low:.1f}-{high:.1f}",
                "risk_score_range": f"{int(low * 100)}-{int(high * 100)}",
                "count": count,
                "predicted_mean": round(float(probabilities[mask].mean()), 4),
                "actual_fraud_rate": round(float(y_true[mask].mean()), 4),
            }
        )

    return table


def format_metrics_report(metrics: ModelMetrics) -> str:
    """Человекочитаемый отчёт для консоли."""
    lines = [
        f"  выборка           : {metrics.samples:,} строк, фрода {metrics.positive_rate:.2%}".replace(",", " "),
        f"  ROC-AUC           : {metrics.roc_auc:.4f}",
        f"  PR-AUC            : {metrics.pr_auc:.4f}   (честнее при дисбалансе)",
        f"  Brier score       : {metrics.brier_score:.5f}   (качество калибровки, меньше — лучше)",
        "",
        "  На пороге 0.50 (обязательные метрики ТЗ §5):",
        f"    precision       : {metrics.default.precision:.4f}",
        f"    recall          : {metrics.default.recall:.4f}",
        f"    F1              : {metrics.default.f1:.4f}",
        f"    TP/FP/FN/TN     : {metrics.default.true_positives} / {metrics.default.false_positives}"
        f" / {metrics.default.false_negatives} / {metrics.default.true_negatives}",
        "",
        f"  Лучший F1 достигается на пороге {metrics.best_f1.threshold:.2f}: "
        f"F1={metrics.best_f1.f1:.4f} (precision={metrics.best_f1.precision:.4f}, "
        f"recall={metrics.best_f1.recall:.4f})",
    ]
    return "\n".join(lines)
