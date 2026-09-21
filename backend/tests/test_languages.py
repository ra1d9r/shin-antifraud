"""Тесты трёх языков клиентского текста (брифинг §6).

Проверяется то, что ломается тихо.

**Ни один язык не забыт.** Пропущенный перевод не падает, а показывает
русскую фразу казахскому клиенту — и заметить это можно только глазами.

**Защита от противоречия вердикту работает на всех языках.** Модель,
которую попросили писать по-казахски, может ответить по-русски, и
проверка обязана поймать «операция отклонена» в обоих случаях.

**Язык не меняет решение.** Он влияет на текст, и только на текст.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.assistant import phrases
from app.assistant.message import DecisionFacts, contradicts, fallback_text
from app.assistant.phrases import LANGUAGES
from app.main import create_app
from app.schemas.enums import Decision


def facts(decision: Decision = Decision.CHALLENGE, reasons: int = 1) -> DecisionFacts:
    return DecisionFacts(
        decision=decision,
        decision_meaning=decision.meaning,
        risk_score=55,
        amount=250000.0,
        merchant="CryptoExchange",
        country="NG",
        reasons=tuple(f"reason {i}" for i in range(reasons)),
        policies=(),
    )


def transaction(**overrides) -> dict:
    body = {
        "user_id": "lang_user",
        "amount": 250000.0,
        "timestamp": "2026-09-01T03:00:00",
        "merchant": "CryptoExchange",
        "country": "NG",
        "device_id": "dev_unknown",
        "ip_address": "45.12.200.7",
        "latitude": 9.05,
        "longitude": 7.49,
        "transaction_frequency": 2,
        "previous_transaction_amount": 95.0,
        "previous_transaction_country": "KZ",
        "account_age_days": 800,
        "user_avg_amount": 100.0,
        "known_device_ids": ["dev_known_1"],
        "persist": False,
    }
    body.update(overrides)
    return body


@pytest.fixture(scope="module")
def client():
    with TestClient(create_app()) as test_client:
        yield test_client


# ------------------------------------------------- ни один язык не забыт


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("decision", list(Decision))
@pytest.mark.parametrize("reasons", [0, 1, 3])
def test_every_combination_produces_text(language, decision, reasons) -> None:
    """Забытый перевод не падает — он показывает чужой язык клиенту."""
    text = fallback_text(facts(decision, reasons), language)

    assert text.strip()
    assert "None" not in text
    assert "{" not in text, "неподставленный шаблон"


@pytest.mark.parametrize("decision", list(Decision))
def test_the_three_languages_differ(decision) -> None:
    """Если два языка совпали дословно, один из переводов забыт."""
    texts = {language: fallback_text(facts(decision), language) for language in LANGUAGES}

    assert len(set(texts.values())) == len(LANGUAGES), texts


@pytest.mark.parametrize("language", LANGUAGES)
def test_prompt_names_the_language(language) -> None:
    """Язык уходит в промпт названием, а не кодом: так модель надёжнее
    отвечает на нужном."""
    prompt = phrases.system_prompt(language)

    assert phrases.LANGUAGE_NAMES[language] in prompt


def test_kazakh_prompt_carries_the_native_name() -> None:
    """«қазақ тілінде» в промпте — подсказка модели, на чём писать."""
    assert "қазақ" in phrases.system_prompt("kk")


# ------------------------------------- защита вердикта на всех языках


@pytest.mark.parametrize(
    ("decision", "text"),
    [
        (Decision.CHALLENGE, "Операция отклонена."),
        (Decision.CHALLENGE, "Операция бұғатталды."),
        (Decision.CHALLENGE, "The payment was declined."),
        (Decision.BLOCK, "Операция успешно проведена."),
        (Decision.BLOCK, "Операция сәтті өтті."),
        (Decision.BLOCK, "The payment was approved."),
    ],
)
def test_contradiction_is_caught_in_any_language(decision, text) -> None:
    """Модель, которую просили писать по-казахски, может ответить
    по-русски — проверка обязана сработать в обоих случаях."""
    assert contradicts(text, decision) is True


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("decision", list(Decision))
def test_our_own_text_never_contradicts_itself(language, decision) -> None:
    """Запасной текст проходит собственную проверку на всех языках.

    Иначе система показывала бы запасной текст, отвергала бы его
    и показывала бы снова — или, что хуже, молча пропускала бы
    противоречие на том языке, слов которого нет в списке.
    """
    assert not contradicts(fallback_text(facts(decision), language), decision)


# --------------------------------------------- язык не меняет решение


@pytest.mark.parametrize("language", LANGUAGES)
def test_language_changes_the_text_not_the_verdict(client, language) -> None:
    body = transaction()
    reference = client.post("/predict", json=body).json()

    payload = client.post(f"/explain/client?language={language}", json=body).json()

    assert payload["language"] == language
    assert payload["decision"] == reference["decision"]
    assert payload["risk_score"] == reference["risk_score"]


def test_default_language_is_russian(client) -> None:
    payload = client.post("/explain/client", json=transaction()).json()

    assert payload["language"] == "ru"


def test_unknown_language_is_refused(client) -> None:
    """Молча подставить русский значило бы соврать полем `language`."""
    response = client.post("/explain/client?language=de", json=transaction())

    assert response.status_code == 422


@pytest.mark.parametrize("language", LANGUAGES)
def test_text_actually_changes_with_the_language(client, language) -> None:
    body = transaction()
    russian = client.post("/explain/client?language=ru", json=body).json()["text"]
    other = client.post(f"/explain/client?language={language}", json=body).json()["text"]

    if language == "ru":
        assert other == russian
    else:
        assert other != russian, "язык выбран, а текст тот же"
