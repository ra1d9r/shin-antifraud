"""Наблюдение за системой в работе: сдвиг распределения признаков.

Отличие от `/analytics/overview` и `/feedback/summary`: тот считает по
датасету, второй — по подтверждённому человеком, а этот сравнивает
**форму входных данных** с той, на которой система строилась. Ответа
«правильно или нет» здесь нет вовсе: есть ответ «похоже ли на то, что
модель видела».
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import DriftDep
from app.schemas.monitoring import DriftReportOut, FeatureDriftOut

router = APIRouter(tags=["monitoring"])


@router.get(
    "/monitoring/drift",
    response_model=DriftReportOut,
    summary="Сдвиг распределения признаков относительно обучающего",
    description=(
        "Population Stability Index по каждому признаку: насколько живой "
        "поток разошёлся с датасетом, на котором система строилась.\n\n"
        "Принятые границы — до 0.1 стабильно, 0.1–0.25 умеренный сдвиг, "
        "дальше существенный. Это отраслевая договорённость скоринга, "
        "а не выведенный из наших данных порог: повод посмотреть, "
        "а не приговор.\n\n"
        "Пока наблюдений меньше минимума, числа не называются — на "
        "полусотне транзакций PSI меряет случайность. Счётчики живут "
        "в памяти и обнуляются при перезапуске: в отличие от разметки "
        "аналитика, их восстанавливает обычный трафик.\n\n"
        "Режим «что если» (`persist=false`) в наблюдение не попадает."
    ),
    responses={503: {"description": "Эталон распределения не выгружен"}},
)
def drift_report(drift: DriftDep) -> DriftReportOut:
    report = drift.report()
    return DriftReportOut(
        status=report.status,
        observed_rows=report.observed_rows,
        baseline_rows=report.baseline_rows,
        baseline_generated_at=report.baseline_generated_at,
        model_trained_at=report.model_trained_at,
        min_observations=report.min_observations,
        enough_data=report.enough_data,
        drifted=report.drifted,
        invalid_values=report.invalid_values,
        features=[
            FeatureDriftOut(
                name=feature.name,
                description=feature.description,
                status=feature.status,
                psi=feature.psi,
                labels=list(feature.labels),
                expected=list(feature.expected),
                observed=list(feature.observed),
            )
            for feature in report.features
        ],
    )
