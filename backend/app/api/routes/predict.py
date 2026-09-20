"""Анализ транзакции (ТЗ §2.1, §15).

Логика цепочки — в `PredictionService`. Здесь к ней добавлена
идемпотентность: повтор по тому же `transaction_id` обслуживается
прежним ответом, и состояние системы при этом не трогается.

Проверка живёт в роуте, а не в сервисе, намеренно. Это свойство
HTTP-контракта — «повторный запрос не повторяет последствий», — а сервис
про HTTP ничего не знает и знать не должен: он умеет обработать
транзакцию, а не решать, обрабатывать ли её вообще.
"""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from app.api.deps import IdempotencyDep, ServiceDep
from app.schemas.prediction import PredictionResponse
from app.schemas.system import ErrorResponse
from app.schemas.transaction import TransactionRequest
from app.store.idempotency import fingerprint

#: Заголовок, которым ответ признаётся повтором. Имя как у платёжных
#: систем — клиенты, которые умеют идемпотентность, ищут именно его.
REPLAY_HEADER = "Idempotent-Replay"

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
        "и профиль не меняются.\n\n"
        "**Повторы безопасны.** Запрос с уже обработанным `transaction_id` "
        "и тем же телом возвращает прежний ответ с заголовком "
        "`Idempotent-Replay: true`, ничего не меняя: операция не попадёт "
        "в историю дважды, профиль клиента не сдвинется, наблюдения "
        "не учтут её повторно.\n\n"
        "Без этого повтор был опасен не только двойным учётом: профиль, "
        "обновлённый первым вызовом, менял ответ на второй — клиент, "
        "переспросивший из-за таймаута, получал другой вердикт по той же "
        "операции.\n\n"
        "Тот же номер с **другими** данными — это вторая операция под "
        "чужим номером, и ответ на неё 409.\n\n"
        "Режим «что если» не кэшируется: он существует ровно для того, "
        "чтобы гонять один и тот же ввод сколько угодно раз."
    ),
    responses={
        409: {"model": ErrorResponse, "description": "Тот же номер, другие данные"},
        422: {"description": "Некорректные данные транзакции"},
        503: {"model": ErrorResponse, "description": "Модель не загружена"},
    },
)
def predict(
    request: TransactionRequest,
    service: ServiceDep,
    idempotency: IdempotencyDep,
    response: Response,
) -> PredictionResponse:
    # Режим «что если» последствий не оставляет, значит и повторять
    # ему нечего.
    if idempotency is None or not request.persist:
        return service.predict(request)

    digest = fingerprint(request.model_dump(mode="json"))
    replayed = idempotency.lookup(request.transaction_id, digest)
    if replayed is not None:
        response.headers[REPLAY_HEADER] = "true"
        return replayed  # type: ignore[return-value]

    result = service.predict(request)
    idempotency.remember(request.transaction_id, digest, result)
    return result
