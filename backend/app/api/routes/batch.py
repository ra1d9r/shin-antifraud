"""Пакетная обработка и порождение потока (брифинг §4.1, §5.B).

Контракт и обоснование двух режимов — в `app/schemas/batch.py`.
Здесь только сборка: прогнать операции через тот же конвейер, что и
одиночный `/predict`, и посчитать сводку.

Отдельного «быстрого пути» без объяснения нет намеренно. Соблазн был:
SHAP считается на каждую операцию и занимает большую часть времени.
Но тогда поток шёл бы не через ту же цепочку, что живой запрос, и
измерял бы не ту систему, которую потом показывают. К тому же
`top_reason` в истории операций брался как раз из объяснения, и без
него таблица транзакций после прогона выглядела бы наполовину пустой.
"""

from __future__ import annotations

import secrets
import time
from collections import Counter
from functools import lru_cache

from fastapi import APIRouter, status

from app.api.deps import IdempotencyDep, ServiceDep
from app.api.routes.predict import _predict_once
from app.core.logging import get_logger
from app.features.builder import parse_device_list
from app.schemas.batch import (
    BatchRequest,
    BatchResponse,
    BatchSummary,
    StreamRequest,
    StreamSummary,
)
from app.schemas.enums import Decision
from app.schemas.prediction import PredictionResponse
from app.schemas.system import ErrorResponse
from app.schemas.transaction import TransactionRequest

logger = get_logger("shin.api.batch")

router = APIRouter(tags=["prediction"])

#: Размер датасета, из которого берётся выборка для потока. Обоснование
#: — в `app/schemas/batch.py`: короткий датасет, порождённый напрямую,
#: даёт ложный дрейф, потому что статистики генератора зависят от объёма.
POOL_ROWS = 10_000
#: Клиентов в пуле. Соотношение то же, что в обучающей выборке
#: (99 360 операций на 3 000 клиентов — около тридцати трёх на человека).
POOL_USERS = 300
#: Зерно пула постоянно: пул — это «данные системы», а не параметр
#: запроса. Меняется только то, какую выборку из него берут.
POOL_SEED = 20260921


@lru_cache(maxsize=1)
def _pool():
    """Датасет, из которого берутся потоки. Строится один раз на процесс.

    Около секунды и восьми мегабайт — дешевле, чем платить за генерацию
    в каждом запросе, и честнее, чем порождать выборку нужного размера
    напрямую.
    """
    from app.ml.dataset import generate_dataset

    logger.info("Готовлю пул для потока: %d операций, %d клиентов", POOL_ROWS, POOL_USERS)
    return generate_dataset(rows=POOL_ROWS, users=POOL_USERS, seed=POOL_SEED)


def _tally(results: list[PredictionResponse]) -> tuple[dict[str, int], dict[str, int], float]:
    """Распределение решений, срабатывания политик и средний балл."""
    decisions = Counter(item.decision.value for item in results)
    rules: Counter[str] = Counter()
    for item in results:
        rules.update(rule.key for rule in item.triggered_rules)

    average = sum(item.risk_score for item in results) / len(results) if results else 0.0
    return dict(decisions), dict(rules), round(average, 2)


@router.post(
    "/predict/batch",
    response_model=BatchResponse,
    status_code=status.HTTP_200_OK,
    summary="Проанализировать партию операций",
    description=(
        "Батч-обработка из брифинга §4.1: «Система принимает транзакцию "
        "(в режиме реального времени через API или батч-обработкой)».\n\n"
        "Каждая операция проходит ту же цепочку, что и одиночный "
        "`/predict`, включая идемпотентность: повторно отправленная "
        "партия не удвоит ни историю, ни профили клиентов. Сколько "
        "операций обслужено повтором, видно в поле `replayed`.\n\n"
        "Порядок ответа совпадает с порядком запроса.\n\n"
        "Партия обрабатывается целиком или не обрабатывается вовсе: "
        "некорректная операция — это 422 на весь запрос, а не частичный "
        "результат с дырками."
    ),
    responses={
        409: {"model": ErrorResponse, "description": "Тот же номер операции, другие данные"},
        422: {"description": "Некорректные данные хотя бы одной операции"},
        503: {"model": ErrorResponse, "description": "Модель не загружена"},
    },
)
def predict_batch(
    request: BatchRequest,
    service: ServiceDep,
    idempotency: IdempotencyDep,
) -> BatchResponse:
    started = time.perf_counter()

    results: list[PredictionResponse] = []
    replayed = 0
    for transaction in request.transactions:
        result, was_replay = _predict_once(transaction, service, idempotency)
        results.append(result)
        replayed += was_replay

    decisions, rules, average = _tally(results)
    elapsed = (time.perf_counter() - started) * 1000.0

    return BatchResponse(
        summary=BatchSummary(
            processed=len(results),
            decisions=decisions,
            average_risk_score=average,
            raised_by_rules=sum(1 for item in results if item.raised_by_rules),
            triggered_rules=rules,
            processing_ms=round(elapsed, 1),
        ),
        replayed=replayed,
        results=results,
    )


@router.post(
    "/predict/stream",
    response_model=StreamSummary,
    status_code=status.HTTP_200_OK,
    summary="Породить поток операций и прогнать его через систему",
    description=(
        "Симуляция потока из брифинга §5.B. Операции порождаются тем же "
        "генератором, на котором обучалась модель, и проходят обычную "
        "цепочку обработки.\n\n"
        "Зачем: наблюдение за дрейфом, теневая конфигурация и граф связей "
        "показывают что-либо только на потоке. На свежем экземпляре "
        "системы эти панели пусты, и понять, работают ли они, нельзя.\n\n"
        "Разметка потока известна — генератор помечает мошеннические "
        "операции, — поэтому сводка показывает не только распределение "
        "решений, но и сколько фрода поймано и сколько пропущено. Это "
        "живая проверка качества, а не число из выгруженного артефакта.\n\n"
        "Операции идут в порядке времени: профиль клиента накапливается "
        "так же, как накапливался бы в проде.\n\n"
        "Идемпотентность здесь не применяется: операции синтетические, "
        "и смысл вызова именно в том, чтобы система поработала."
    ),
    responses={503: {"model": ErrorResponse, "description": "Модель не загружена"}},
)
def predict_stream(request: StreamRequest, service: ServiceDep) -> StreamSummary:
    seed = request.seed if request.seed is not None else secrets.randbelow(2**31)

    started = time.perf_counter()
    pool = _pool()
    # Порядок времени важен: профиль обновляется после каждой операции,
    # и в перемешанном потоке «новое устройство» срабатывало бы наугад.
    frame = pool.sample(min(request.count, len(pool)), random_state=seed)
    frame = frame.sort_values("timestamp")
    results: list[PredictionResponse] = []
    fraud_flags: list[bool] = []
    for row in frame.to_dict("records"):
        is_fraud = bool(row.pop("is_fraud", False))
        results.append(service.predict(_to_request(row)))
        fraud_flags.append(is_fraud)

    decisions, rules, average = _tally(results)
    stopped = sum(
        1
        for item, fraud in zip(results, fraud_flags, strict=True)
        if fraud and item.decision is not Decision.APPROVE
    )
    false_positives = sum(
        1
        for item, fraud in zip(results, fraud_flags, strict=True)
        if not fraud and item.decision is not Decision.APPROVE
    )
    fraud_total = sum(fraud_flags)
    elapsed = (time.perf_counter() - started) * 1000.0

    logger.info(
        "Поток прогнан: %d операций, фрода %d, поймано %d, зерно %d",
        len(results), fraud_total, stopped, seed,
    )

    return StreamSummary(
        requested=request.count,
        processed=len(results),
        seed=seed,
        pool_rows=len(pool),
        decisions=decisions,
        average_risk_score=average,
        raised_by_rules=sum(1 for item in results if item.raised_by_rules),
        triggered_rules=rules,
        fraud_in_stream=fraud_total,
        fraud_stopped=stopped,
        fraud_missed=fraud_total - stopped,
        false_positives=false_positives,
        processing_ms=round(elapsed, 1),
    )


def _to_request(row: dict) -> TransactionRequest:
    """Строка порождённого потока -> запрос на анализ.

    Колонки генератора названы так же, как поля запроса, поэтому берутся
    только известные схеме, а лишние (`fraud_scenario`,
    `txn_count_last_24h`) отбрасываются.

    Две поправки. Пропущенное значение в кадре — это NaN или NaT, а схема
    ждёт либо значение, либо отсутствие поля; такие ключи убираются.
    И список известных устройств генератор хранит строкой через `|`,
    а схема ждёт список.
    """
    import pandas as pd

    known = TransactionRequest.model_fields
    clean: dict[str, object] = {}
    for key, value in row.items():
        if key not in known or value is None:
            continue
        # `pd.isna` на списке вернул бы массив, поэтому проверяются
        # только скаляры — у списков пропусков не бывает по построению.
        if not isinstance(value, list | tuple) and pd.isna(value):
            continue
        clean[key] = value

    clean["known_device_ids"] = list(parse_device_list(row.get("known_device_ids")))
    return TransactionRequest(**clean)
