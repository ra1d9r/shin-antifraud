"""Анализ транзакции (ТЗ §2.1, §15).

Роут делает ровно три вещи: принимает провалидированную схему, вызывает
сервис и возвращает результат. Вся логика — в `PredictionService`.
"""

from __future__ import annotations

from fastapi import APIRouter, status

from app.api.deps import ServiceDep
from app.schemas.prediction import PredictionResponse
from app.schemas.system import ErrorResponse
from app.schemas.transaction import TransactionRequest

router = APIRouter(tags=["prediction"])


@router.post(
    "/predict",
    response_model=PredictionResponse,
    status_code=status.HTTP_200_OK,
    summary="Проанализировать транзакцию",
    description=(
        "Полная цепочка: feature engineering -> ML-модель -> Risk Score -> "
        "Risk Engine -> решение -> объяснение.\n\n"
        "Ответ содержит **и** `model_score` (чистый выход модели), **и** "
        "`risk_score` (после политик), поэтому видно, что подняло риск.\n\n"
        "Контекст клиента можно передать явно (`user_avg_amount`, "
        "`known_device_ids`, `previous_*`) — тогда ответ не зависит от "
        "накопленной истории и повторный запрос даёт тот же результат. "
        "Если контекст не передан, он берётся из профиля клиента.\n\n"
        "`persist: false` — режим «что если»: ответ считается, но история "
        "и профиль не меняются."
    ),
    responses={
        422: {"description": "Некорректные данные транзакции"},
        503: {"model": ErrorResponse, "description": "Модель не загружена"},
    },
)
def predict(request: TransactionRequest, service: ServiceDep) -> PredictionResponse:
    return service.predict(request)
