"""Граф связей между клиентами — то, чего не видно по одной операции.

Все остальные эндпоинты смотрят на транзакции по отдельности. Кольцо
мошенников так не найти: поодиночке его участники выглядят безупречно,
и увидеть их можно только вместе.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import TransactionsDep
from app.graph.clusters import build_clusters
from app.schemas.graph import ClusterOut, ClusterReportOut

router = APIRouter(tags=["graph"])


@router.get(
    "/graph/clusters",
    response_model=ClusterReportOut,
    summary="Клиенты, связанные общим устройством или подсетью",
    description=(
        "Строит граф по буферу обработанных операций: клиенты, их "
        "устройства и подсети /24. Группы, где клиентов больше одного, "
        "и есть кандидаты в кольца.\n\n"
        "**Почему по живому потоку, а не по датасету.** В сгенерированных "
        "данных колец нет по построению: идентификаторы устройств "
        "собираются как `dev_{номер клиента}_{n}`, то есть пространство "
        "имён разделено по клиентам. Из 8 414 устройств датасета у более "
        "чем одного клиента ровно одно, общих подсетей — ноль. Кольца "
        "и положено искать по недавней активности.\n\n"
        "**Связи не равнозначны.** Общее устройство объясняется плохо. "
        "Общую подсеть делят корпоративный NAT, оператор мобильной связи "
        "и один провайдер в одном доме — такие группы помечены "
        "`SUBNET_ONLY` и сами по себе почти ничего не значат.\n\n"
        "Сводной «оценки подозрительности» здесь нет: её пришлось бы "
        "придумать, взвесив число клиентов против суммы, и вес был бы "
        "взят с потолка. Показаны факты.\n\n"
        "Граф ничего не меняет в решениях — это анализ, а не политика."
    ),
)
def graph_clusters(
    transactions: TransactionsDep,
    min_size: Annotated[
        int, Query(ge=2, le=100, description="С какого числа клиентов группа интересна")
    ] = 2,
) -> ClusterReportOut:
    report = build_clusters(transactions.all(), min_size=min_size)
    return ClusterReportOut(
        scanned_transactions=report.scanned_transactions,
        known_users=report.known_users,
        linked_users=report.linked_users,
        weak_clusters=report.weak_clusters,
        clusters=[
            ClusterOut(
                users=list(cluster.users),
                size=cluster.size,
                shared_devices=list(cluster.shared_devices),
                shared_subnets=list(cluster.shared_subnets),
                strength=cluster.strength,
                transactions=cluster.transactions,
                flagged=cluster.flagged,
                total_amount=cluster.total_amount,
                max_risk_score=cluster.max_risk_score,
            )
            for cluster in report.clusters
        ],
    )
