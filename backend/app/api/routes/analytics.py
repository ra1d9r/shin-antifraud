"""Аналитика по всему датасету — источник данных для дашборда."""

from __future__ import annotations

from fastapi import APIRouter

from app.analytics.report import EvaluationNotFoundError
from app.api.deps import StateDep
from app.schemas.analytics import AnalyticsOverview

router = APIRouter(tags=["analytics"])


@router.get(
    "/analytics/overview",
    response_model=AnalyticsOverview,
    summary="Сводная аналитика по всему потоку транзакций",
    description=(
        "Отличается от `GET /stats`: тот считает по операциям, реально "
        "прошедшим через систему за время её работы, а этот — по всему "
        "датасету, где известна разметка. Поэтому здесь есть то, чего "
        "в проде не бывает: сколько фрода пропущено и скольких "
        "добросовестных клиентов система побеспокоила зря.\n\n"
        "Расчёт тяжёлый (около двадцати секунд на 100 000 транзакций), "
        "поэтому выполняется заранее скриптом `export_evaluation.py`, "
        "а эндпоинт отдаёт готовый артефакт. Если артефакта нет, "
        "ответ — 503 с указанием команды."
    ),
    responses={503: {"description": "Аналитика не выгружена"}},
)
def analytics_overview(state: StateDep) -> AnalyticsOverview:
    if state.evaluation is None:
        raise EvaluationNotFoundError(
            state.evaluation_error
            or (
                "Аналитика не выгружена. Выполните: "
                "python backend/scripts/export_evaluation.py"
            )
        )
    return AnalyticsOverview(**state.evaluation)
