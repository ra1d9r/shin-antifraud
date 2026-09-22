"""Тесты справочника признаков (ТЗ §4, брифинг §5.B).

Справочник существует, чтобы числа в векторе перестали быть безымянными.
Поэтому проверяется соответствие: каждому числу есть описание, у каждого
описания есть число, и порядок тот же, что у колонок модели.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.features.definitions import FEATURE_NAMES, FEATURE_SPECS
from app.features.geo import is_datacenter_ip
from app.i18n import LANGUAGES
from app.main import create_app


@pytest.fixture(scope="module")
def client():
    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def registry(client):
    return client.get("/features").json()


def transaction(**overrides) -> dict:
    body = {
        "user_id": "user_features",
        "amount": 100.0,
        "timestamp": "2026-09-01T14:30:00",
        "merchant": "Magnum",
        "country": "KZ",
        "device_id": "dev_known_1",
        "ip_address": "85.132.10.55",
        "latitude": 51.16,
        "longitude": 71.44,
        "transaction_frequency": 3,
        "previous_transaction_amount": 95.0,
        "previous_transaction_country": "KZ",
        "account_age_days": 800,
        "persist": False,
    }
    body.update(overrides)
    return body


# ------------------------------------------------------------- реестр


def test_every_feature_has_a_section() -> None:
    """Раздел обязателен в датаклассе, забыть его нельзя по построению.

    Раньше соответствие жило отдельным списком в скрипте документации,
    и новый признак можно было в него не добавить.
    """
    for spec in FEATURE_SPECS:
        assert spec.section, f"{spec.name} без раздела ТЗ"
        # Номер пункта ТЗ одинаков на всех трёх языках: это ссылка
        # на документ, а не текст. Перевод, потерявший номер, оставил бы
        # читателя без способа найти первоисточник.
        for language in LANGUAGES:
            section = spec.section.get(language)
            assert section.startswith("§4"), f"{spec.name}/{language}: раздел «{section}»"


def test_registry_covers_the_whole_vector(registry) -> None:
    listed = [item["name"] for section in registry["sections"] for item in section["features"]]

    assert registry["count"] == len(FEATURE_NAMES)
    assert listed == list(FEATURE_NAMES), "порядок обязан совпадать с вектором модели"


def test_indexes_match_the_column_order(registry) -> None:
    """Индекс — это позиция колонки. Разойдись он с реестром, подпись
    в интерфейсе встала бы напротив чужого числа."""
    for section in registry["sections"]:
        for item in section["features"]:
            assert FEATURE_NAMES[item["index"]] == item["name"]


def test_sections_keep_vector_order(registry) -> None:
    """Сортировка по названию разорвала бы группы, которые считаются вместе."""
    first_indexes = [section["features"][0]["index"] for section in registry["sections"]]

    assert first_indexes == sorted(first_indexes)


def test_descriptions_are_filled(registry) -> None:
    for section in registry["sections"]:
        for item in section["features"]:
            assert item["description"].strip(), f'{item["name"]} без описания'
            assert item["reason_high"].strip(), f'{item["name"]} без формулировки XAI'


def test_flags_and_decimals_are_consistent(registry) -> None:
    by_name = {spec.name: spec for spec in FEATURE_SPECS}

    for section in registry["sections"]:
        for item in section["features"]:
            spec = by_name[item["name"]]
            assert item["is_flag"] is spec.is_flag
            assert item["decimals"] == spec.decimals
            assert 0 <= item["decimals"] <= 4


# --------------------------------- то, что искал проверяющий (§5.B)


@pytest.mark.parametrize(
    ("name", "wanted"),
    [
        ("amount_deviation_ratio", "расчет отклонений от среднего чека"),
        ("travel_speed_kmh", "скорости перемещения между IP"),
    ],
)
def test_the_features_named_in_the_brief_are_findable(registry, name, wanted) -> None:
    """Брифинг §5.B называет эти две величины поимённо.

    Считались они с самого начала, но увидеть их было негде: вектор
    приходит без подписей, а объяснение показывает только пять сильнейших.
    Проверяющий их искал и не нашёл — значит они обязаны быть в справочнике.
    """
    listed = {item["name"]: item for s in registry["sections"] for item in s["features"]}

    assert name in listed, f"{name} — {wanted}"
    assert listed[name]["description"].strip()


def test_registry_keys_match_the_prediction_vector(client, registry) -> None:
    """Смысл справочника: по ключу число соединяется со своим описанием.

    Разойдись имена — интерфейс показал бы описания без значений
    и значения без описаний, и никто бы не понял почему.
    """
    features = client.post("/predict", json=transaction()).json()["features"]
    listed = {item["name"] for section in registry["sections"] for item in section["features"]}

    assert listed == set(features)


# ------------------------------------ VPN/прокси (пример из брифинга)


def test_vpn_feature_recognises_datacenter_addresses() -> None:
    """Признак ловит адреса из списка и не трогает обычные."""
    assert is_datacenter_ip("203.0.113.7")
    assert is_datacenter_ip("185.220.101.5")
    assert not is_datacenter_ip("85.132.10.55")


@pytest.mark.parametrize("value", ["", None, "1.2", "не адрес"])
def test_vpn_feature_survives_garbage(value) -> None:
    """Мусор в поле адреса — не повод падать в середине оценки риска."""
    assert is_datacenter_ip(value) is False


def test_vpn_feature_reaches_the_vector(client) -> None:
    """Признак обязан доезжать до вектора, а не жить в реестре.

    Проверяется на двух адресах: иначе тест прошёл бы и на признаке,
    который всегда возвращает одно и то же.
    """
    through_vpn = client.post(
        "/predict", json=transaction(ip_address="203.0.113.7", persist=False)
    ).json()
    from_home = client.post(
        "/predict", json=transaction(ip_address="85.132.10.55", persist=False)
    ).json()

    assert through_vpn["features"]["is_vpn_ip"] == 1.0
    assert from_home["features"]["is_vpn_ip"] == 0.0


def test_vpn_alone_does_not_decide(client) -> None:
    """VPN — не улика, и одного его мало для задержания.

    Им пользуются в поездках и в офисах. Если бы признак решал сам,
    система задерживала бы каждого осторожного клиента — а в обучающих
    данных мошенническая лишь каждая пятая операция из-под VPN.
    """
    payload = client.post(
        "/predict", json=transaction(ip_address="203.0.113.7", persist=False)
    ).json()

    assert payload["features"]["is_vpn_ip"] == 1.0
    assert payload["decision"] == "APPROVE", (
        f"обычная операция задержана только за VPN: {payload['risk_score']}"
    )
