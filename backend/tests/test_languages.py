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

from app.api.routes.predict import REPLAY_HEADER
from app.assistant import phrases
from app.assistant.message import DecisionFacts, contradicts, fallback_text, written_in
from app.i18n import LANGUAGES
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


# ------------------------------------ язык в остальных эндпоинтах (5б)
#
# Интерфейс переведён, но часть текста он получает готовым с backend:
# описания признаков, пояснение к решению, описания сценариев. Пока
# `?language=` не было, английский дашборд показывал 27 русских строк.


ENDPOINTS_WITH_TEXT = [
    ("/features", "get"),
    ("/scenarios", "get"),
    ("/monitoring/drift", "get"),
]


def feature_descriptions(payload: dict) -> list[str]:
    return [item["description"] for section in payload["sections"] for item in section["features"]]


@pytest.mark.parametrize("language", LANGUAGES)
def test_features_follow_the_requested_language(client, language) -> None:
    payload = client.get(f"/features?language={language}").json()

    russian = feature_descriptions(client.get("/features?language=ru").json())
    current = feature_descriptions(payload)

    assert len(current) == len(russian)
    if language == "ru":
        assert current == russian
    else:
        assert current != russian, "язык выбран, а описания те же"
        assert all(text.strip() for text in current), "пустое описание вместо перевода"


@pytest.mark.parametrize("language", LANGUAGES)
def test_feature_names_never_translate(client, language) -> None:
    """По имени число вектора соединяется с описанием (см. /features).

    Переведи его — и связь порвётся: интерфейс покажет описания без
    значений и значения без описаний.
    """
    russian = client.get("/features?language=ru").json()
    current = client.get(f"/features?language={language}").json()

    names = lambda payload: [  # noqa: E731
        item["name"] for section in payload["sections"] for item in section["features"]
    ]
    assert names(current) == names(russian)


@pytest.mark.parametrize("language", LANGUAGES)
def test_scenarios_follow_the_requested_language(client, language) -> None:
    items = client.get(f"/scenarios?language={language}").json()["items"]
    russian = client.get("/scenarios?language=ru").json()["items"]

    assert [item["key"] for item in items] == [item["key"] for item in russian]
    # Названия сценариев технические: по ним их ищут в документации.
    assert [item["title"] for item in items] == [item["title"] for item in russian]

    if language != "ru":
        assert [item["description"] for item in items] != [
            item["description"] for item in russian
        ], "язык выбран, а описания те же"


@pytest.mark.parametrize("language", LANGUAGES)
def test_decision_meaning_follows_the_language(client, language) -> None:
    payload = client.post(f"/predict?language={language}", json=transaction()).json()

    assert payload["language"] == language
    assert payload["decision_meaning"].strip()

    russian = client.post("/predict?language=ru", json=transaction()).json()
    if language != "ru":
        assert payload["decision_meaning"] != russian["decision_meaning"]


@pytest.mark.parametrize("language", LANGUAGES)
def test_language_never_moves_the_verdict(client, language) -> None:
    """Главный инвариант: перевод — это текст, и только текст.

    Стоит языку задеть решение или оценку — и система начнёт судить
    по-разному в зависимости от того, на каком языке её спросили.
    """
    body = transaction()
    russian = client.post("/predict?language=ru", json=body).json()
    current = client.post(f"/predict?language={language}", json=body).json()

    assert current["decision"] == russian["decision"]
    assert current["risk_score"] == russian["risk_score"]
    assert current["risk_level"] == russian["risk_level"]
    assert current["features"] == russian["features"]
    assert [rule["key"] for rule in current["triggered_rules"]] == [
        rule["key"] for rule in russian["triggered_rules"]
    ]


@pytest.mark.parametrize(("path", "method"), ENDPOINTS_WITH_TEXT)
def test_unknown_language_is_refused_everywhere(client, path, method) -> None:
    """Молча подставить русский значило бы соврать о языке ответа."""
    response = getattr(client, method)(f"{path}?language=de")

    assert response.status_code == 422, path


def test_repeat_in_another_language_translates_without_reprocessing(client) -> None:
    """Идемпотентный повтор отдаёт тот же ответ, но на запрошенном языке.

    Язык не входит в отпечаток намеренно: иначе тот же платёж, посланный
    по-русски и по-английски, обработался бы дважды — удвоив историю
    и сдвинув профили.
    """
    body = transaction(transaction_id="txn_lang_replay", persist=True)

    first = client.post("/predict?language=ru", json=body)
    second = client.post("/predict?language=en", json=body)

    assert second.headers.get(REPLAY_HEADER) == "true", "повтор не распознан"
    assert second.json()["decision"] == first.json()["decision"]
    assert second.json()["risk_score"] == first.json()["risk_score"]
    assert second.json()["language"] == "en"
    assert second.json()["decision_meaning"] != first.json()["decision_meaning"]


# ------------------------------- ответ модели на запрошенном языке


#: Настоящие ответы не на том языке. Китайский — не выдумка: модели,
#: которых просят писать по-казахски, иногда отвечают на языке,
#: которого в их обучающих данных было больше всего.
WRONG_LANGUAGE = [
    ("kk", "我们已暂停该笔交易，请您确认操作。", "китайский вместо казахского"),
    ("kk", "We have put the payment on hold until you confirm it.", "английский"),
    ("kk", "Мы приостановили операцию до вашего подтверждения.", "русский"),
    ("ru", "操作已被阻止，请联系银行。", "китайский вместо русского"),
    ("ru", "We have put the payment on hold.", "английский вместо русского"),
    ("en", "操作已被阻止。", "китайский вместо английского"),
    ("en", "Мы приостановили операцию до вашего подтверждения.", "русский"),
]


@pytest.mark.parametrize("language", LANGUAGES)
def test_our_own_text_passes_the_language_check(language) -> None:
    """Защита обязана пропускать правильные ответы.

    Проверка, отвергающая наш собственный текст, заменила бы работающий
    ассистент запасным навсегда — и заметить это было бы нечем.
    """
    for decision in (Decision.CHALLENGE, Decision.BLOCK):
        text = fallback_text(facts(decision), language)
        assert written_in(text, language), f"{language}/{decision}: свой же текст не прошёл"


@pytest.mark.parametrize(("language", "text", "note"), WRONG_LANGUAGE)
def test_wrong_language_is_caught(language, text, note) -> None:
    assert not written_in(text, language), note


def test_kazakh_is_told_apart_from_russian() -> None:
    """Самая вероятная подмена — русский вместо казахского.

    Обе письменности кириллические, и проверкой по алфавиту их
    не различить. Различают буквы, которых в русском нет.
    """
    kazakh = "Операцияны сіз растағанша тоқтата тұрдық. Ақша есептен шығарылған жоқ."
    russian = "Операцию приостановили до вашего подтверждения. Деньги не списаны."

    assert written_in(kazakh, "kk")
    assert not written_in(russian, "kk")
    # А как русский тот же текст проходит — язык проверяется, а не запрещается.
    assert written_in(russian, "ru")


def test_merchant_name_in_latin_does_not_break_a_kazakh_answer() -> None:
    """Название мерчанта приходит латиницей и остаётся в тексте.

    Требовать чистой кириллицы значило бы отвергать правильные ответы:
    «CryptoExchange» на казахский не переводится.
    """
    text = "«CryptoExchange» атына сомасындағы операцияны сіз растағанша тоқтата тұрдық."

    assert written_in(text, "kk")


@pytest.mark.parametrize("text", ["", "   ", "\n\n", "12345 67890", "!!! ???"])
def test_text_without_words_is_refused(text) -> None:
    """Показывать клиенту нечего — значит показываем запасной текст."""
    assert not written_in(text, "ru")


@pytest.mark.parametrize("language", LANGUAGES)
def test_prompt_demands_the_language_more_than_once(language) -> None:
    """Одной строки в конце списка правил модели мало.

    Требование стоит первым, повторено в конце и подкреплено примером —
    иначе казахский сползает на русский чаще, чем хотелось бы.
    """
    prompt = phrases.system_prompt(language)
    name = phrases.LANGUAGE_NAMES[language]

    assert prompt.count(name) >= 3, "язык упомянут меньше трёх раз"
    assert prompt.startswith("Отвечай ТОЛЬКО"), "требование языка не первое"
    assert phrases.LANGUAGE_EXAMPLES[language] in prompt, "нет примера правильного ответа"


@pytest.mark.parametrize("language", LANGUAGES)
def test_prompt_example_is_itself_in_the_right_language(language) -> None:
    """Пример на чужом языке учил бы модель ровно тому, что запрещает."""
    assert written_in(phrases.LANGUAGE_EXAMPLES[language], language)
