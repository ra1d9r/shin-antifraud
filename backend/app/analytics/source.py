"""Откуда берутся данные для аналитики.

Вынесено из скриптов: и печать отчёта в консоль, и выгрузка артефакта
нуждаются в одном и том же — датасете, модели и вероятностях. Пока это
жило внутри `evaluate_risk_engine.py`, второй потребитель был обязан
скопировать логику, включая восстановление датасета.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config.settings import Settings
from app.core.exceptions import ModelNotLoadedError
from app.core.logging import get_logger
from app.ml.dataset import generate_dataset
from app.ml.pipeline import load_model, prepare_training_data

logger = get_logger("shin.analytics.source")

DATE_COLUMNS = ["timestamp", "previous_timestamp"]


@dataclass(frozen=True, slots=True)
class EvaluationInputs:
    """Всё, на чём считается отчёт."""

    frame: Any
    features: Any
    labels: Any
    probabilities: Any
    model: Any


def ensure_dataset(settings: Settings, dataset_path: Path, *, explicit: bool) -> None:
    """Убедиться, что датасет на месте, иначе восстановить его.

    Внутри Docker-образа CSV удаляется сразу после обучения: он весит 25 МБ
    и иначе навсегда остался бы в истории слоёв. Восстанавливаем тем же
    генератором и тем же зерном — данные получаются ровно те, на которых
    обучалась модель, это закреплено тестом
    `test_dataset.py::test_generation_is_deterministic_across_processes`.

    Args:
        explicit: путь назвали явно в аргументах. Тогда отсутствие файла —
            ошибка пользователя, и создавать вместо него другой набор данных
            было бы хуже, чем отказать.
    """
    if dataset_path.exists():
        return
    if explicit:
        raise FileNotFoundError(f"Датасет не найден: {dataset_path}")

    logger.info(
        "Датасет не найден (%s) — генерирую заново с зерном %s",
        dataset_path,
        settings.random_seed,
    )
    restored = generate_dataset(
        rows=settings.dataset_rows,
        users=settings.dataset_users,
        fraud_rate=settings.dataset_fraud_rate,
        seed=settings.random_seed,
    )
    dataset_path.parent.mkdir(parents=True, exist_ok=True)
    restored.to_csv(dataset_path, index=False)


def prepare_inputs(
    settings: Settings,
    *,
    dataset_path: Path | None = None,
    model_path: Path | None = None,
    limit: int | None = None,
) -> EvaluationInputs:
    """Собрать датасет, модель и вероятности.

    Args:
        limit: взять случайную подвыборку такого размера. Нужно скриптам
            для быстрых прогонов; для артефакта берётся весь датасет.
    """
    import pandas as pd

    resolved_dataset = dataset_path or settings.dataset_file
    resolved_model = model_path or settings.model_file

    ensure_dataset(settings, resolved_dataset, explicit=dataset_path is not None)

    if not resolved_model.exists():
        raise ModelNotLoadedError(
            f"Модель не найдена: {resolved_model}. "
            "Выполните: python backend/scripts/train_model.py"
        )

    frame = pd.read_csv(resolved_dataset, parse_dates=DATE_COLUMNS)
    if limit and len(frame) > limit:
        frame = frame.sample(limit, random_state=0).reset_index(drop=True)

    features, labels = prepare_training_data(frame)
    model = load_model(resolved_model)

    return EvaluationInputs(
        frame=frame,
        features=features,
        labels=labels,
        probabilities=model.predict_proba(features),
        model=model,
    )
