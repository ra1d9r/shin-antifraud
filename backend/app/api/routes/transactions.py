"""Список обработанных транзакций с фильтрами (ТЗ §8.2).

Эндпоинт добавлен сверх обязательных трёх — решение
[D-5](../../../../docs/TZ.md): таблица Dashboard с фильтрацией по decision,
risk score, country и статусу требует источника данных.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import FeedbackDep, TransactionsDep
from app.schemas.enums import Decision, RiskLevel
from app.schemas.system import TransactionListResponse, TransactionRecordOut

router = APIRouter(tags=["transactions"])


@router.get(
    "/transactions",
    response_model=TransactionListResponse,
    summary="Обработанные транзакции",
    description=(
        "Последние обработанные транзакции, от новых к старым, с фильтрами "
        "по решению, уровню риска, стране, диапазону Risk Score и клиенту."
    ),
)
def list_transactions(
    transactions: TransactionsDep,
    feedback: FeedbackDep,
    decision: Annotated[Decision | None, Query(description="Фильтр по решению")] = None,
    risk_level: Annotated[RiskLevel | None, Query(description="Фильтр по уровню риска")] = None,
    country: Annotated[str | None, Query(min_length=2, max_length=2)] = None,
    min_risk_score: Annotated[int | None, Query(ge=0, le=100)] = None,
    max_risk_score: Annotated[int | None, Query(ge=0, le=100)] = None,
    user_id: Annotated[str | None, Query(description="Фильтр по клиенту")] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> TransactionListResponse:
    total, records = transactions.query(
        decision=decision,
        risk_level=risk_level,
        country=country,
        min_risk_score=min_risk_score,
        max_risk_score=max_risk_score,
        user_id=user_id,
        limit=limit,
        offset=offset,
    )

    # Разметка подмешивается одним словарём на страницу, а не запросом
    # за меткой на строку: буфер меток невелик, а O(n*m) на таблице
    # в тысячу строк заметно даже локально.
    labels = {label.transaction_id: label for label in feedback.all()}

    items = []
    for record in records:
        label = labels.get(record.transaction_id)
        items.append(
            TransactionRecordOut(
                transaction_id=record.transaction_id,
                user_id=record.user_id,
                timestamp=record.timestamp,
                amount=record.amount,
                country=record.country,
                merchant=record.merchant,
                device_id=record.device_id,
                risk_score=record.risk_score,
                model_score=record.model_score,
                decision=record.decision,
                risk_level=record.risk_level,
                triggered_rules=list(record.triggered_rules),
                top_reason=record.top_reason,
                verdict=label.verdict if label else None,
                actual_fraud=label.actual_fraud if label else None,
            )
        )

    return TransactionListResponse(total=total, returned=len(items), items=items)
