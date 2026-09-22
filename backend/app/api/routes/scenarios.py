"""Готовые сценарии ручного тестирования (ТЗ §9).

Эндпоинты добавлены сверх обязательных — решение
[D-5](../../../../docs/TZ.md). Они закрывают требование ТЗ §9 о том, что
сценарии должны прогоняться руками: в Swagger достаточно нажать
*Try it out* на `POST /scenarios/{key}/run`, а симулятор (этап 11)
подставляет те же данные кнопкой-пресетом.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, Query

from app.api.deps import ServiceDep
from app.i18n import DEFAULT_LANGUAGE, Language
from app.schemas.enums import ScenarioKey
from app.schemas.prediction import PredictionResponse
from app.schemas.system import ScenarioListResponse, ScenarioOut
from app.services.scenarios import SCENARIOS, get_scenario

router = APIRouter(tags=["scenarios"])


def _to_out(scenario, language: Language) -> ScenarioOut:
    return ScenarioOut(
        key=scenario.key,
        # Название переводится: это подпись кнопки в симуляторе, то есть
        # продуктовая поверхность. Искать сценарий в документации и в
        # тестах всё равно по `key` — он и остаётся неизменным.
        title=scenario.title.get(language),
        description=scenario.description.get(language),
        expectation=scenario.expectation.get(language),
        changed_from_normal=list(scenario.changed_from_normal),
        transaction=scenario.to_transaction(),
    )


@router.get(
    "/scenarios",
    response_model=ScenarioListResponse,
    summary="Сценарии ручного тестирования",
    description=(
        "Пять сценариев из ТЗ §9 — от обычной покупки до явной атаки. "
        "Все описывают одного клиента: меняется ровно то, что заявлено "
        "в названии, поэтому Risk Score между ними сравним.\n\n"
        "Профиль и метки времени заданы явно, так что результат "
        "воспроизводится независимо от истории и времени запуска."
    ),
)
def list_scenarios(language: Language = DEFAULT_LANGUAGE) -> ScenarioListResponse:
    return ScenarioListResponse(
        items=[_to_out(scenario, language) for scenario in SCENARIOS]
    )


@router.get(
    "/scenarios/{key}",
    response_model=ScenarioOut,
    summary="Один сценарий",
    description="Тело запроса сценария — его можно скопировать в POST /predict.",
)
def read_scenario(
    key: Annotated[ScenarioKey, Path(description="Ключ сценария")],
    language: Language = DEFAULT_LANGUAGE,
) -> ScenarioOut:
    return _to_out(get_scenario(key), language)


@router.post(
    "/scenarios/{key}/run",
    response_model=PredictionResponse,
    summary="Прогнать сценарий через /predict",
    description=(
        "Выполняет ту же цепочку, что и `POST /predict`, на данных сценария. "
        "Удобно для ручной проверки: один запрос вместо копирования тела.\n\n"
        "По умолчанию результат попадает в историю и статистику — так "
        "прогон сценариев наполняет Dashboard. Передайте `persist=false`, "
        "чтобы посчитать ответ, не меняя состояние системы."
    ),
)
def run_scenario(
    key: Annotated[ScenarioKey, Path(description="Ключ сценария")],
    service: ServiceDep,
    persist: Annotated[bool, Query(description="Сохранять ли результат в историю")] = True,
    language: Language = DEFAULT_LANGUAGE,
) -> PredictionResponse:
    transaction = get_scenario(key).to_transaction()
    transaction.persist = persist
    return service.predict(transaction, language)
