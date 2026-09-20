"""Граф связей: клиенты, связанные общим устройством или подсетью.

## Зачем

Все остальные части системы смотрят на операцию по отдельности: признаки
описывают одну транзакцию, модель оценивает одну транзакцию, политики
проверяют одну транзакцию. Мошенническое кольцо так не видно в принципе.

Десять «разных» клиентов, заходящих с одного устройства, поодиночке
выглядят безупречно: сумма обычная, страна привычная, устройство для
каждого из них своё привычное. Увидеть их можно только вместе.

## Почему по живому потоку, а не по датасету

В сгенерированном датасете колец нет **по построению**: идентификаторы
устройств собираются как `dev_{номер клиента}_{n}`, то есть пространство
имён разделено по клиентам и пересечься не может. IP-префикс тоже у
каждого свой. Проверено на 99 360 строках: из 8 414 устройств у более
чем одного клиента ровно одно, общих подсетей — ноль.

Поэтому граф строится по буферу обработанных операций. Это и есть
правильное место: кольца ищут по недавней активности, а не по обучающей
выборке.

## Насколько связь что-то значит

**Общее устройство — сильная связь.** Один физический телефон у трёх
«разных» людей объясняется плохо.

**Общая подсеть /24 — слабая.** Её делят корпоративный NAT, оператор
мобильной связи, один провайдер в одном доме. Сама по себе она не
значит почти ничего, и выдавать её за улику нельзя.

Поэтому связи не смешиваются в одно число: у каждой группы видно, чем
именно она связана, а группы, склеенные только подсетью, помечены как
слабые.

## Чего здесь намеренно нет

Сводной «оценки подозрительности» группы. Её пришлось бы придумать —
взвесить число клиентов против суммы против доли помеченных, — и вес
был бы взят с потолка. Показаны факты, по которым аналитик решает сам,
а порядок задан размером группы и суммой.

Граф также ничего не меняет в решениях: это анализ, а не политика.
Правило «клиент делит устройство с заблокированным» напрашивается,
но оно уже влияло бы на клиентов и требует отдельного разговора.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from enum import StrEnum

from app.schemas.enums import Decision
from app.store.transactions import TransactionRecord

#: Решения, которыми система объявляет операцию подозрительной.
FLAGGED = frozenset({Decision.CHALLENGE, Decision.BLOCK})


class LinkStrength(StrEnum):
    """Чем связана группа и насколько этому можно верить."""

    #: Есть общее устройство — объясняется плохо.
    DEVICE = "DEVICE"
    #: Только общая подсеть — её делят NAT, оператор, провайдер.
    SUBNET_ONLY = "SUBNET_ONLY"


class _DisjointSet:
    """Система непересекающихся множеств со сжатием путей.

    Построение групп — это ровно задача «объединяй и ищи»: каждая
    операция объединяет клиента с его устройством и подсетью, а группы
    получаются сами. Обход графа в ширину дал бы то же, но потребовал бы
    сначала собрать списки смежности — лишняя структура того же размера.
    """

    def __init__(self) -> None:
        self._parent: dict[str, str] = {}

    def find(self, node: str) -> str:
        parent = self._parent.setdefault(node, node)
        if parent == node:
            return node
        root = self.find(parent)
        self._parent[node] = root
        return root

    def union(self, left: str, right: str) -> None:
        left_root, right_root = self.find(left), self.find(right)
        if left_root != right_root:
            self._parent[left_root] = right_root


@dataclass(frozen=True, slots=True)
class Cluster:
    """Группа клиентов, связанных общими устройствами или подсетями."""

    users: tuple[str, ...]
    shared_devices: tuple[str, ...]
    shared_subnets: tuple[str, ...]
    strength: LinkStrength
    transactions: int
    flagged: int
    total_amount: float
    max_risk_score: int

    @property
    def size(self) -> int:
        return len(self.users)


@dataclass(frozen=True, slots=True)
class ClusterReport:
    """Что нашлось в графе связей по буферу операций."""

    scanned_transactions: int
    known_users: int
    clusters: tuple[Cluster, ...]
    #: Группы, связанные только подсетью, — их легко объяснить и без фрода.
    weak_clusters: int
    linked_users: int


def build_clusters(records: list[TransactionRecord], *, min_size: int = 2) -> ClusterReport:
    """Собрать группы связанных клиентов.

    Args:
        records: операции из буфера обработанных.
        min_size: с какого числа клиентов группа интересна. Один клиент
            со своими устройствами — не группа, а обычная жизнь.
    """
    disjoint = _DisjointSet()
    users: set[str] = set()

    # Узлы разнесены по пространствам имён: клиент `u1` и устройство
    # с тем же идентификатором не должны схлопнуться в один узел.
    for record in records:
        user = f"user:{record.user_id}"
        users.add(record.user_id)
        disjoint.union(user, f"device:{record.device_id}")
        if record.ip_subnet:
            disjoint.union(user, f"subnet:{record.ip_subnet}")

    grouped_users: dict[str, set[str]] = defaultdict(set)
    grouped_devices: dict[str, set[str]] = defaultdict(set)
    grouped_subnets: dict[str, set[str]] = defaultdict(set)
    grouped_records: dict[str, list[TransactionRecord]] = defaultdict(list)

    # Устройство или подсеть считаются общими, только если ими пользуется
    # больше одного клиента. Иначе в списке улик оказался бы личный телефон.
    device_users: dict[str, set[str]] = defaultdict(set)
    subnet_users: dict[str, set[str]] = defaultdict(set)
    for record in records:
        device_users[record.device_id].add(record.user_id)
        if record.ip_subnet:
            subnet_users[record.ip_subnet].add(record.user_id)

    for record in records:
        root = disjoint.find(f"user:{record.user_id}")
        grouped_users[root].add(record.user_id)
        grouped_records[root].append(record)
        if len(device_users[record.device_id]) > 1:
            grouped_devices[root].add(record.device_id)
        if record.ip_subnet and len(subnet_users[record.ip_subnet]) > 1:
            grouped_subnets[root].add(record.ip_subnet)

    clusters: list[Cluster] = []
    for root, members in grouped_users.items():
        if len(members) < min_size:
            continue

        group = grouped_records[root]
        devices = tuple(sorted(grouped_devices[root]))
        subnets = tuple(sorted(grouped_subnets[root]))

        clusters.append(
            Cluster(
                users=tuple(sorted(members)),
                shared_devices=devices,
                shared_subnets=subnets,
                strength=LinkStrength.DEVICE if devices else LinkStrength.SUBNET_ONLY,
                transactions=len(group),
                flagged=sum(1 for item in group if item.decision in FLAGGED),
                total_amount=round(sum(item.amount for item in group), 2),
                max_risk_score=max(item.risk_score for item in group),
            )
        )

    # Порядок: сначала крупные группы, потом дорогие. Сводной «оценки
    # подозрительности» здесь нет намеренно — см. docstring модуля.
    clusters.sort(key=lambda item: (-item.size, -item.total_amount, item.users[0]))

    return ClusterReport(
        scanned_transactions=len(records),
        known_users=len(users),
        clusters=tuple(clusters),
        weak_clusters=sum(
            1 for item in clusters if item.strength is LinkStrength.SUBNET_ONLY
        ),
        linked_users=sum(item.size for item in clusters),
    )
