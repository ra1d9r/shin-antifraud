"""Статистика по обработанным транзакциям (ТЗ §2.1, §8.1)."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import TransactionsDep
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
        "Это оценка системы: подтверждённой разметки в реальном потоке нет."
    ),
)
def stats(transactions: TransactionsDep) -> StatsResponse:
    payload = transactions.statistics()
    return StatsResponse(
        **{**payload, "decisions": DecisionBreakdown(**payload["decisions"])}
    )
