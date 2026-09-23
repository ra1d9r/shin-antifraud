"""Разметка аналитика: единственный канал настоящих меток в работающей системе.

Остальные эндпоинты рассказывают, что система **думает**. Этот — что
оказалось правдой. Из накопленного получается измеренное качество
(а не оценка по обучающему датасету) и заготовка обучающей выборки
на следующий цикл.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Path, Query

from app.api.deps import FeedbackDep, TransactionsDep
from app.core.exceptions import TransactionNotFoundError
from app.schemas.feedback import (
    DecisionFeedbackOut,
    FeedbackAccepted,
    FeedbackListResponse,
    FeedbackOut,
    FeedbackRequest,
    FeedbackSummary,
    RuleFeedbackOut,
)
from app.store.feedback import FeedbackRecord, FeedbackStore, derive_actual_fraud

router = APIRouter(tags=["feedback"])


def _to_out(record: FeedbackRecord) -> FeedbackOut:
    return FeedbackOut(
        transaction_id=record.transaction_id,
        user_id=record.user_id,
        verdict=record.verdict,
        actual_fraud=record.actual_fraud,
        decision=record.decision,
        risk_score=record.risk_score,
        model_score=record.model_score,
        amount=record.amount,
        triggered_rules=list(record.triggered_rules),
        labeled_at=record.labeled_at,
        analyst=record.analyst,
        comment=record.comment,
    )


def _summary_out(store: FeedbackStore) -> FeedbackSummary:
    summary = store.summary()
    return FeedbackSummary(
        labeled_total=summary.labeled_total,
        correct=summary.correct,
        incorrect=summary.incorrect,
        correct_share=summary.correct_share,
        fraud_confirmed=summary.fraud_confirmed,
        legit_confirmed=summary.legit_confirmed,
        true_positive=summary.true_positive,
        false_positive=summary.false_positive,
        true_negative=summary.true_negative,
        false_negative=summary.false_negative,
        precision=summary.precision,
        recall=summary.recall,
        fraud_amount_missed=summary.fraud_amount_missed,
        by_decision=[
            DecisionFeedbackOut(
                decision=row.decision, labeled=row.labeled, fraud=row.fraud, legit=row.legit
            )
            for row in summary.by_decision
        ],
        rules=[
            RuleFeedbackOut(key=row.key, labeled=row.labeled, fraud=row.fraud, legit=row.legit)
            for row in summary.rules
        ],
        storage_path=summary.storage_path,
        storage_error=summary.storage_error,
        skipped_lines=summary.skipped_lines,
    )


@router.post(
    "/transactions/{transaction_id}/feedback",
    response_model=FeedbackAccepted,
    summary="Отметить вердикт системы верным или ошибочным",
    description=(
        "Аналитик разобрал операцию и сообщает, права ли была система. "
        "Из отметки выводится настоящая метка: при CHALLENGE и BLOCK "
        "«верно» означает подтверждённый фрод, «ошибочно» — ложное "
        "срабатывание; при APPROVE наоборот.\n\n"
        "Метка сохраняется вместе со слепком решения — Risk Score, "
        "вердиктом и сработавшими политиками. Буфер обработанных "
        "транзакций ограничен, и к моменту дообучения самой операции "
        "в памяти уже не будет.\n\n"
        "Повторная разметка той же операции заменяет прежнюю."
    ),
    responses={404: {"description": "Операции нет в истории обработанных"}},
)
def submit_feedback(
    payload: FeedbackRequest,
    transactions: TransactionsDep,
    feedback: FeedbackDep,
    transaction_id: Annotated[str, Path(description="Идентификатор обработанной операции")],
) -> FeedbackAccepted:
    transaction = transactions.get(transaction_id)
    if transaction is None:
        # Причины две, и различить их изнутри нельзя: операцию могли
        # посчитать с `persist=false` (в историю она не попала) либо
        # вытеснить из кольцевого буфера. Говорим обе — иначе аналитик
        # будет искать опечатку в идентификаторе, которого там и не было.
        raise TransactionNotFoundError(
            f"Операция {transaction_id} не найдена среди последних "
            f"{transactions.capacity} обработанных. Возможно, она считалась "
            "без сохранения в историю (persist=false) или уже вытеснена "
            "из буфера.",
            details={"transaction_id": transaction_id, "buffer_capacity": transactions.capacity},
        )

    record = FeedbackRecord(
        transaction_id=transaction.transaction_id,
        user_id=transaction.user_id,
        verdict=payload.verdict,
        actual_fraud=derive_actual_fraud(transaction.decision, payload.verdict),
        decision=transaction.decision,
        risk_score=transaction.risk_score,
        model_score=transaction.model_score,
        amount=transaction.amount,
        triggered_rules=transaction.triggered_rules,
        labeled_at=datetime.now(UTC).replace(tzinfo=None),
        analyst=payload.analyst,
        comment=payload.comment,
    )
    feedback.add(record)

    return FeedbackAccepted(record=_to_out(record), summary=_summary_out(feedback))


@router.get(
    "/feedback/summary",
    response_model=FeedbackSummary,
    summary="Измеренное качество по разметке аналитика",
    description=(
        "Матрица ошибок и точность, посчитанные по подтверждённым меткам, "
        "а не по обучающему датасету.\n\n"
        "**Оговорка о смещении.** Размеченное — не случайная выборка: "
        "аналитик разбирает то, что система пометила. Поэтому точность "
        "(precision) здесь осмысленна, а полнота (recall) смещена вверх — "
        "пропущенный фрод попадает в разметку, только когда о нём сообщил "
        "клиент. Сравнивать её с полнотой из `GET /model` нельзя."
    ),
)
def feedback_summary(feedback: FeedbackDep) -> FeedbackSummary:
    return _summary_out(feedback)


@router.get(
    "/feedback",
    response_model=FeedbackListResponse,
    summary="Накопленная разметка",
    description=(
        "Метки от свежих к старым. Каждая — готовая строка обучающей "
        "выборки: признаки решения и подтверждённый исход.\n\n"
        "На хостинге с эфемерным диском это единственный способ забрать "
        "разметку до того, как контейнер погаснет."
    ),
)
def list_feedback(
    feedback: FeedbackDep,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> FeedbackListResponse:
    records = feedback.all()
    page = records[offset : offset + limit]
    return FeedbackListResponse(
        total=len(records),
        returned=len(page),
        items=[_to_out(record) for record in page],
    )
