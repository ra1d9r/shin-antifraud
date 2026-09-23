"""Контракты графа связей.

Домен живёт в `app.graph.clusters`; здесь только то, что уходит в HTTP.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.graph.clusters import LinkStrength


class ClusterOut(BaseModel):
    """Группа клиентов, связанных общими устройствами или подсетями."""

    users: list[str]
    size: int = Field(description="Сколько клиентов в группе")
    shared_devices: list[str] = Field(
        default_factory=list,
        description="Устройства, которыми пользуется больше одного клиента",
    )
    shared_subnets: list[str] = Field(
        default_factory=list, description="Подсети /24, общие для нескольких клиентов"
    )
    strength: LinkStrength = Field(
        description=(
            "DEVICE — есть общее устройство, объясняется плохо. "
            "SUBNET_ONLY — только общая подсеть, а её делят корпоративный NAT, "
            "оператор связи и один провайдер в одном доме."
        )
    )
    transactions: int
    flagged: int = Field(description="Сколько операций группы система пометила")
    total_amount: float
    max_risk_score: int


class ClusterReportOut(BaseModel):
    """Что нашлось в графе связей.

    Строится по буферу обработанных операций, а не по датасету: в
    сгенерированных данных колец нет по построению — идентификаторы
    устройств там разделены по клиентам и пересечься не могут.
    """

    scanned_transactions: int = Field(description="Сколько операций просмотрено")
    known_users: int = Field(description="Сколько разных клиентов в них встретилось")
    linked_users: int = Field(description="Сколько клиентов попало хотя бы в одну группу")
    weak_clusters: int = Field(
        description="Групп, связанных только подсетью, — их легко объяснить и без фрода"
    )
    clusters: list[ClusterOut] = Field(
        default_factory=list,
        description="По убыванию размера, затем суммы. Сводной оценки подозрительности нет",
    )
