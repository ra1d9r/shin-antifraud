"""Статистика по обработанным транзакциям (ТЗ §2.1, §8.1)."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import StateDep, TransactionsDep
from app.schemas.system import DecisionBreakdown, StatsResponse

router = APIRouter(tags=["system"])


@router.get(
    "/stats",
    response_model=StatsResponse,
    summary="Статистика по обработанным транзакциям",
    description=(
        "Считается по тому, что реально прошло через систему за время её "
        "работы, а не по обучающему датасету.\n\n"
        "`fraud_rate` — доля транзакций с решением, отличным от `APPROVE`. "
        "Это оценка системы: подтверждённой разметки в реальном потоке нет. "
        "Подтверждённые числа — в `GET /feedback/summary`."
    ),
)
def stats(transactions: TransactionsDep, state: StateDep) -> StatsResponse:
    payload = transactions.statistics()
    # История операций при смене порогов не чистится: в ней лежат
    # операции, которые аналитику ещё размечать, и граф связей строится
    # по ней же. Но молчать о смене нельзя — числа охватывают две
    # конфигурации, и без пометки их прочитают как одно измерение.
    changes = state.threshold_changes
    return StatsResponse(
        **{**payload, "decisions": DecisionBreakdown(**payload["decisions"])},
        thresholds_changed_at=changes[0]["at"] if changes else None,
    )
