"""Тесты графа связей.

Главный риск здесь — ложное обвинение. Группа собирается из настоящих
клиентов, и назвать кольцом людей, которые просто сидят за одним NAT,
хуже, чем не найти ничего. Поэтому проверяется не только «находит»,
но и «не находит там, где нечего находить».
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.features.builder import ip_subnet
from app.graph.clusters import LinkStrength, build_clusters
from app.main import create_app
from app.schemas.enums import Decision, RiskLevel
from app.store.transactions import TransactionRecord

BASE = datetime(2026, 9, 20, 12, 0, 0)


def record(
    user: str,
    device: str,
    *,
    subnet: str | None = "85.132.10",
    amount: float = 100.0,
    score: int = 10,
    decision: Decision = Decision.APPROVE,
    minutes: int = 0,
) -> TransactionRecord:
    return TransactionRecord(
        transaction_id=f"txn_{user}_{device}_{minutes}",
        user_id=user,
        timestamp=BASE + timedelta(minutes=minutes),
        amount=amount,
        country="KZ",
        merchant="Magnum",
        device_id=device,
        risk_score=score,
        model_score=score,
        decision=decision,
        risk_level=RiskLevel.LOW,
        triggered_rules=(),
        top_reason=None,
        ip_subnet=subnet,
    )


# ------------------------------------------------- определение подсети


def test_subnet_is_the_first_three_octets() -> None:
    assert ip_subnet("85.132.10.55") == "85.132.10"
    assert ip_subnet(None) is None


def test_graph_and_feature_share_one_definition() -> None:
    """Вторая копия «первых трёх октетов» разошлась бы с этой.

    Тогда признак `ip_subnet_changed` перестал бы означать то же,
    что рёбра графа, и объяснить расхождение было бы нечем.
    """
    from app.features import builder

    assert builder.ip_subnet is ip_subnet


# --------------------------------------------- когда группы быть не должно


def test_one_user_with_many_devices_is_not_a_group() -> None:
    """Обычная жизнь: телефон, ноутбук, планшет — не кольцо."""
    records = [
        record("u1", "dev_a", minutes=0),
        record("u1", "dev_b", minutes=1),
        record("u1", "dev_c", minutes=2),
    ]

    report = build_clusters(records)

    assert report.clusters == ()
    assert report.linked_users == 0
    assert report.known_users == 1


def test_separate_users_on_separate_devices_stay_separate() -> None:
    records = [
        record("u1", "dev_a", subnet="85.132.10"),
        record("u2", "dev_b", subnet="77.55.1", minutes=1),
    ]

    assert build_clusters(records).clusters == ()


def test_personal_device_is_not_listed_as_shared() -> None:
    """Иначе в списке улик оказался бы личный телефон каждого."""
    records = [
        record("u1", "dev_shared"),
        record("u2", "dev_shared", minutes=1),
        record("u1", "dev_personal", minutes=2),
    ]

    cluster = build_clusters(records).clusters[0]

    assert cluster.shared_devices == ("dev_shared",)
    assert "dev_personal" not in cluster.shared_devices


def test_empty_history_gives_an_empty_report() -> None:
    report = build_clusters([])

    assert report.clusters == ()
    assert (report.scanned_transactions, report.known_users) == (0, 0)


# ------------------------------------------------------ когда группа есть


def test_shared_device_links_users() -> None:
    records = [
        record("u1", "dev_ring", subnet="1.1.1", amount=500.0),
        record("u2", "dev_ring", subnet="2.2.2", amount=300.0, minutes=1),
        record("u3", "dev_ring", subnet="3.3.3", amount=200.0, minutes=2),
    ]

    report = build_clusters(records)
    cluster = report.clusters[0]

    assert cluster.users == ("u1", "u2", "u3")
    assert cluster.shared_devices == ("dev_ring",)
    assert cluster.strength is LinkStrength.DEVICE
    assert cluster.total_amount == 1000.0
    assert report.linked_users == 3


def test_link_travels_through_the_chain() -> None:
    """Связь транзитивна: у u1 и u3 общего устройства нет, но кольцо одно.

    Ровно это и не видно по одной операции: попарно ничего, а вместе —
    группа из трёх.
    """
    records = [
        record("u1", "dev_x", subnet=None),
        record("u2", "dev_x", subnet=None, minutes=1),
        record("u2", "dev_y", subnet=None, minutes=2),
        record("u3", "dev_y", subnet=None, minutes=3),
    ]

    clusters = build_clusters(records).clusters

    assert len(clusters) == 1
    assert clusters[0].users == ("u1", "u2", "u3")
    assert clusters[0].shared_devices == ("dev_x", "dev_y")


def test_subnet_only_group_is_marked_weak() -> None:
    """Общий NAT — не улика, и выдавать его за неё нельзя."""
    records = [
        record("u1", "dev_a", subnet="10.0.0"),
        record("u2", "dev_b", subnet="10.0.0", minutes=1),
    ]

    report = build_clusters(records)
    cluster = report.clusters[0]

    assert cluster.strength is LinkStrength.SUBNET_ONLY
    assert cluster.shared_devices == ()
    assert cluster.shared_subnets == ("10.0.0",)
    assert report.weak_clusters == 1


def test_device_link_outweighs_subnet_in_labelling() -> None:
    """Если общее устройство есть, группа сильная, даже когда есть и подсеть."""
    records = [
        record("u1", "dev_ring", subnet="10.0.0"),
        record("u2", "dev_ring", subnet="10.0.0", minutes=1),
    ]

    cluster = build_clusters(records).clusters[0]

    assert cluster.strength is LinkStrength.DEVICE
    assert cluster.shared_subnets == ("10.0.0",)


def test_flagged_and_risk_are_summarised_per_group() -> None:
    records = [
        record("u1", "dev_ring", decision=Decision.BLOCK, score=95),
        record("u2", "dev_ring", decision=Decision.APPROVE, score=10, minutes=1),
        record("u3", "dev_ring", decision=Decision.CHALLENGE, score=55, minutes=2),
    ]

    cluster = build_clusters(records).clusters[0]

    assert cluster.transactions == 3
    # CHALLENGE и BLOCK — оба «система сочла операцию подозрительной».
    assert cluster.flagged == 2
    assert cluster.max_risk_score == 95


def test_bigger_groups_come_first() -> None:
    records = [
        record("a1", "dev_pair", amount=10_000.0, subnet=None),
        record("a2", "dev_pair", amount=10_000.0, subnet=None, minutes=1),
        record("b1", "dev_trio", subnet=None, minutes=2),
        record("b2", "dev_trio", subnet=None, minutes=3),
        record("b3", "dev_trio", subnet=None, minutes=4),
    ]

    clusters = build_clusters(records).clusters

    # Размер важнее суммы: пара на 20 000 стоит ниже тройки на 300.
    assert clusters[0].size == 3
    assert clusters[1].size == 2


def test_min_size_raises_the_bar() -> None:
    records = [
        record("u1", "dev_pair", subnet=None),
        record("u2", "dev_pair", subnet=None, minutes=1),
    ]

    assert build_clusters(records, min_size=2).clusters != ()
    assert build_clusters(records, min_size=3).clusters == ()


def test_user_and_device_with_the_same_name_do_not_merge() -> None:
    """Узлы разнесены по пространствам имён, иначе схлопнулись бы в один."""
    records = [
        record("same", "other", subnet=None),
        record("other_user", "same", subnet=None, minutes=1),
    ]

    assert build_clusters(records).clusters == ()


# -------------------------------------------------------------- HTTP-слой


@pytest.fixture(scope="module")
def client():
    with TestClient(create_app()) as test_client:
        yield test_client


def transaction(**overrides) -> dict:
    body = {
        "user_id": "user_graph",
        "amount": 100.0,
        "timestamp": "2026-09-01T14:30:00",
        "merchant": "Magnum",
        "country": "KZ",
        "device_id": "dev_graph",
        "ip_address": "85.132.10.55",
        "latitude": 51.16,
        "longitude": 71.44,
        "transaction_frequency": 3,
        "previous_transaction_amount": 95.0,
        "previous_transaction_country": "KZ",
        "account_age_days": 800,
    }
    body.update(overrides)
    return body


def test_endpoint_finds_a_ring_built_through_the_api(client) -> None:
    """Так это и демонстрируется: три операции с одного устройства."""
    client.app.state.shin.transactions.clear()

    for index in (1, 2, 3):
        client.post(
            "/predict",
            json=transaction(
                transaction_id=f"txn_ring_{index}",
                user_id=f"ring_user_{index}",
                device_id="dev_one_phone",
            ),
        )

    payload = client.get("/graph/clusters").json()

    assert payload["scanned_transactions"] == 3
    assert len(payload["clusters"]) == 1
    cluster = payload["clusters"][0]
    assert cluster["size"] == 3
    assert cluster["shared_devices"] == ["dev_one_phone"]
    assert cluster["strength"] == "DEVICE"


def test_endpoint_is_quiet_on_ordinary_traffic(client) -> None:
    client.app.state.shin.transactions.clear()

    for index in (1, 2, 3):
        client.post(
            "/predict",
            json=transaction(
                transaction_id=f"txn_alone_{index}",
                user_id=f"alone_{index}",
                device_id=f"dev_alone_{index}",
                ip_address=f"85.132.{index}.55",
            ),
        )

    payload = client.get("/graph/clusters").json()

    assert payload["known_users"] == 3
    assert payload["clusters"] == []


def test_transactions_table_shows_the_subnet_not_the_address(client) -> None:
    """Графу нужна подсеть, а полный адрес хранить незачем."""
    client.app.state.shin.transactions.clear()
    client.post("/predict", json=transaction(transaction_id="txn_subnet"))

    row = client.get("/transactions").json()["items"][0]

    assert row["ip_subnet"] == "85.132.10"
    assert "ip_address" not in row
