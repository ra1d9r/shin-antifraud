"""Отчёт по операции текстом — то, что аналитик приложит к тикету.

Отдельный эндпоинт, а не поле в `POST /predict`: отчёт — страница текста
на полтора килобайта, и возвращать её каждому клиенту API, включая тех,
кому нужен только Risk Score, было бы расточительством без повода.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

from app.api.deps import ServiceDep, StateDep
from app.reports.transaction import render_transaction_report
from app.schemas.transaction import TransactionRequest

router = APIRouter(tags=["report"])


@router.post(
    "/report",
    response_class=PlainTextResponse,
    summary="Отчёт по операции текстом",
    description=(
        "Одна страница, которую можно скопировать целиком: в тикет, "
        "в письмо клиентской службе, в обоснование решения по обращению.\n\n"
        "Тело запроса то же, что у `POST /predict`. Ответ — `text/plain`.\n\n"
        "**Отчёт ничего не меняет.** Поле `persist` игнорируется: "
        "составление отчёта — чтение, а не обработка, и операция от него "
        "не попадёт ни в историю, ни в профиль клиента, ни в наблюдение "
        "за дрейфом. Иначе аналитик, перечитавший обоснование трижды, "
        "трижды бы добавил операцию в статистику.\n\n"
        "Оценка считается заново, поэтому отчёт всегда соответствует "
        "текущей модели и текущим порогам, а не тем, что были на момент "
        "исходного решения."
    ),
    responses={
        200: {
            "content": {"text/plain": {}},
            "description": "Готовый отчёт",
        },
        503: {"description": "Модель не загружена"},
    },
)
def transaction_report(
    request: TransactionRequest,
    service: ServiceDep,
    state: StateDep,
) -> PlainTextResponse:
    # Копия без сохранения: клиент мог прислать persist=true, но отчёт
    # состоянием системы не распоряжается.
    read_only = request.model_copy(update={"persist": False})
    response = service.predict(read_only)

    text = render_transaction_report(
        read_only,
        response,
        model_algorithm=state.model.algorithm if state.model else None,
        model_trained_at=state.model.trained_at if state.model else None,
    )
    return PlainTextResponse(text, media_type="text/plain; charset=utf-8")
