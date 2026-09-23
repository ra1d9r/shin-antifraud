"""Аналитика по всему датасету — источник данных для дашборда."""

from __future__ import annotations

from fastapi import APIRouter

from app.analytics.report import EvaluationNotFoundError
from app.api.deps import StateDep, analytics_drift
from app.i18n import DEFAULT_LANGUAGE, Language
from app.schemas.analytics import AnalyticsOverview

router = APIRouter(tags=["analytics"])


def _translated(state: StateDep, language: Language) -> dict:
    """Отчёт с названиями политик на запрошенном языке.

    Артефакт хранит название той политики, что действовала при выгрузке,
    и хранит его одной строкой — на языке, который был по умолчанию
    в момент выгрузки. Показывается оно в подсказке к таблице политик,
    и на английском виде подсказка была русской.

    Перевод берётся не из артефакта, а из действующего набора правил
    по ключу: ключ технический и не переводится никогда, а название
    у правила лежит сразу на трёх языках. Если правило из набора убрали,
    остаётся то, что записано в артефакте, — оно описывает числа рядом,
    и подменять его нечем.
    """
    report = dict(state.evaluation or {})
    rows = report.get("rules")
    if not rows:
        return report

    engine = state.risk_engine
    titles = {rule.key: rule.title for rule in engine.rules} if engine else {}
    report["rules"] = [
        {**row, "title": titles[row["key"]].get(language)} if row.get("key") in titles else row
        for row in rows
    ]
    return report


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
def analytics_overview(
    state: StateDep,
    language: Language = DEFAULT_LANGUAGE,
) -> AnalyticsOverview:
    if state.evaluation is None:
        raise EvaluationNotFoundError(
            state.evaluation_error
            or (
                "Аналитика не выгружена. Выполните: "
                "python backend/scripts/export_evaluation.py"
            )
        )
    # Свежесть считается при каждом чтении, а не хранится флагом.
    #
    # Несовпадение с моделью выясняется один раз на старте: модель
    # в рантайме не меняется. А настройки меняются, и меняются в обе
    # стороны — поэтому они сверяются здесь. Пока это был флаг, правку
    # нельзя было отменить: отчёт, снова совпадающий с настройками
    # до последнего числа, числился устаревшим до перезапуска.
    reason = state.evaluation_stale_reason or analytics_drift(state)
    return AnalyticsOverview(
        **_translated(state, language),
        stale=reason is not None,
        stale_reason=reason.get(language) if reason else None,
    )
