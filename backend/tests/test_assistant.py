"""Тесты LLM-ассистента (брифинг §6).

Проверяется четыре вещи, и первые две важнее остальных.

**Ключ не утекает.** Он не должен появляться ни в ответе, ни в сообщении
об ошибке, ни в логе. Ошибка от провайдера приходит с телом, в котором
может быть эхо запроса — вместе с заголовком авторизации.

**Решение принимает модель, а не ассистент.** Языковая модель получает
готовые факты и не может изменить вердикт. Если её ответ противоречит
решению, показывается запасной текст: для клиента «операция отклонена»
и «подтвердите операцию» — совершенно разные новости.

Дальше — что система работает без ключа вовсе, и что в запрос не уезжает
лишнего.

Сеть не трогается ни разу: `httpx.post` подменяется.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from app.assistant import llm as llm_module
from app.assistant.llm import LlmClient, LlmConfig, LlmUnavailableError
from app.assistant.message import (
    DecisionFacts,
    build_facts,
    contradicts,
    fallback_text,
    needs_assistant,
)
from app.config.settings import Settings
from app.main import create_app
from app.schemas.enums import Decision

#: Заведомо поддельный ключ. Намеренно не в форме `sk-...`:
#: строка такого вида в репозитории цепляет сканеры секретов
#: и заставляет человека перепроверять, не настоящий ли это ключ.
SECRET = "TEST-KEY-NOT-A-REAL-SECRET"


def transaction(**overrides) -> dict:
    body = {
        "user_id": "assistant_user",
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


def facts(decision: Decision = Decision.CHALLENGE) -> DecisionFacts:
    return DecisionFacts(
        decision=decision,
        decision_meaning=decision.meaning,
        risk_score=55,
        amount=250000.0,
        merchant="CryptoExchange",
        country="NG",
        reasons=("Transaction from an unusual country",),
        policies=("Transaction from a high-risk country",),
    )


def config(api_key: str = SECRET) -> LlmConfig:
    return LlmConfig(
        api_key=api_key,
        base_url="https://llm.example",
        model="test-model",
        timeout_seconds=1.0,
        max_tokens=100,
    )


@pytest.fixture(scope="module")
def client():
    with TestClient(create_app()) as test_client:
        yield test_client


# ------------------------------------------------------- ключ не утекает


def test_key_is_hidden_in_the_settings_repr() -> None:
    """`SecretStr`, а не `str`: иначе ключ печатался бы в каждом логе настроек."""
    settings = Settings(llm_api_key=SECRET)

    assert SECRET not in repr(settings)
    assert SECRET not in str(settings)
    assert settings.llm_api_key.get_secret_value() == SECRET


def test_provider_error_body_never_reaches_the_caller(monkeypatch) -> None:
    """Тело ответа провайдера наружу не уходит.

    Провайдер вправе вернуть в нём эхо запроса — вместе с заголовком
    авторизации. Сообщение собирается из кода состояния.
    """
    def fake_post(*args, **kwargs):
        return httpx.Response(
            401,
            json={"error": "invalid key", "echo": {"Authorization": f"Bearer {SECRET}"}},
            request=httpx.Request("POST", "https://llm.example/chat/completions"),
        )

    monkeypatch.setattr(llm_module.httpx, "post", fake_post)

    with pytest.raises(LlmUnavailableError) as failure:
        LlmClient(config()).complete("system", "user")

    assert SECRET not in failure.value.message
    assert "401" in failure.value.message


def test_network_error_message_is_built_from_the_exception_type(monkeypatch) -> None:
    """Текст исключения httpx содержит URL, а через него — параметры запроса."""
    def fake_post(*args, **kwargs):
        raise httpx.ConnectError(f"failed connecting with token {SECRET}")

    monkeypatch.setattr(llm_module.httpx, "post", fake_post)

    with pytest.raises(LlmUnavailableError) as failure:
        LlmClient(config()).complete("system", "user")

    assert SECRET not in failure.value.message
    assert "ConnectError" in failure.value.message


def test_the_key_is_sent_only_in_the_authorization_header(monkeypatch) -> None:
    captured: dict = {}

    def fake_post(url, *, json, headers, timeout):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "готово"}}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(llm_module.httpx, "post", fake_post)
    LlmClient(config()).complete("system", "user")

    assert captured["headers"]["Authorization"] == f"Bearer {SECRET}"
    assert SECRET not in str(captured["json"])
    assert SECRET not in captured["url"]


# --------------------------------------- решение принимает не ассистент


@pytest.mark.parametrize(
    ("decision", "generated"),
    [
        (Decision.CHALLENGE, "Ваша операция заблокирована, обратитесь в банк."),
        (Decision.CHALLENGE, "Операция отклонена службой безопасности."),
        (Decision.BLOCK, "Операция успешно проведена."),
    ],
)
def test_text_contradicting_the_verdict_is_refused(decision, generated) -> None:
    """Перепутать «отклонена» и «подтвердите» хуже, чем не написать ничего."""
    assert contradicts(generated, decision) is True


@pytest.mark.parametrize(
    ("decision", "generated"),
    [
        (Decision.CHALLENGE, "Мы приостановили операцию. Подтвердите её в приложении."),
        (Decision.BLOCK, "Мы не пропустили операцию, деньги остались на счёте."),
    ],
)
def test_matching_text_passes(decision, generated) -> None:
    assert contradicts(generated, decision) is False


def test_contradicting_answer_falls_back(client, monkeypatch) -> None:
    """Сквозная проверка: ответ модели, спорящий с вердиктом, не показывается."""
    def fake_post(url, *, json, headers, timeout):
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "Операция отклонена."}}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(llm_module.httpx, "post", fake_post)
    monkeypatch.setattr(
        client.app.state.shin.settings, "llm_api_key", Settings(llm_api_key=SECRET).llm_api_key
    )

    payload = client.post("/explain/client", json=transaction()).json()

    # Вердикт закреплён явно: с `if` проверка молча пропускала бы себя,
    # если бы операция однажды перестала давать CHALLENGE.
    assert payload["decision"] == "CHALLENGE"
    assert payload["source"] == "fallback"
    assert "противоречил" in payload["fallback_reason"]
    assert "отклонена" not in payload["text"].lower()


# --------------------------------------------- работа без языковой модели


def test_without_a_key_the_answer_is_still_produced(client) -> None:
    """Ключа в тестовом окружении нет — ответ обязан быть полноценным."""
    payload = client.post("/explain/client", json=transaction()).json()

    assert payload["source"] == "fallback"
    assert payload["text"].strip()
    assert payload["fallback_reason"], "причина запасного текста обязана называться"
    assert payload["model"] is None


def test_the_answer_never_pretends_to_be_written_by_a_model(client) -> None:
    """Выдавать шаблон за работу ассистента — заявлять то, чего нет."""
    payload = client.post("/explain/client", json=transaction()).json()

    # В тестовом окружении ключа нет, значит текст обязан быть запасным
    # и обязан в этом признаваться.
    assert payload["source"] == "fallback"
    assert payload["model"] is None


def test_unconfigured_client_does_not_touch_the_network(monkeypatch) -> None:
    def explode(*args, **kwargs):
        raise AssertionError("без ключа сеть трогать нельзя")

    monkeypatch.setattr(llm_module.httpx, "post", explode)

    with pytest.raises(LlmUnavailableError) as failure:
        LlmClient(config(api_key="")).complete("system", "user")

    assert "LLM_API_KEY" in failure.value.message


@pytest.mark.parametrize("decision", list(Decision))
def test_fallback_text_covers_every_decision(decision) -> None:
    text = fallback_text(facts(decision))

    assert text.strip()
    assert not contradicts(text, decision), "запасной текст спорит сам с собой"


def test_fallback_text_does_not_paste_analyst_wording_to_the_client() -> None:
    """XAI формулирует причины по-английски и для аналитика.

    «Transaction from a high-risk country» в письме клиенту банк
    отправить не может, а перевод здесь завёл бы вторую версию каждой
    формулировки. Запасной текст говорит, сколько сигналов сработало,
    и не притворяется подробным.
    """
    built = facts(Decision.CHALLENGE)
    text = fallback_text(built)

    for reason in built.reasons:
        assert reason not in text
    assert "один необычный признак" in text


def test_approved_transaction_does_not_call_the_model() -> None:
    """Одобренную операцию клиент не замечает — платить за вызов не за что."""
    assert needs_assistant(Decision.APPROVE) is False
    assert needs_assistant(Decision.CHALLENGE) is True
    assert needs_assistant(Decision.BLOCK) is True


# ------------------------------------------- что уезжает на чужой сервер


def test_the_prompt_carries_no_identifiers(client) -> None:
    """В запрос уходят только факты решения.

    Идентификатор клиента, номер операции и IP языковой модели не нужны,
    а уезжают они на чужой сервер.
    """
    body = transaction(user_id="ivan_petrov", transaction_id="txn_secret_42")
    payload = client.post("/explain/client", json=body).json()
    block = "\n".join(payload["facts"])

    assert "ivan_petrov" not in block
    assert "txn_secret_42" not in block
    assert "45.12.200.7" not in block
    assert "CryptoExchange" in block, "а вот получатель клиенту как раз важен"


def test_facts_come_from_the_decision(client) -> None:
    body = transaction()
    prediction = client.post("/predict", json=body).json()
    message = client.post("/explain/client", json=body).json()

    assert message["decision"] == prediction["decision"]
    assert message["risk_score"] == prediction["risk_score"]


def test_explaining_changes_nothing(client) -> None:
    """Объяснение — чтение. Аналитик, перечитавший его трижды, не должен
    трижды добавить операцию в статистику."""
    state = client.app.state.shin
    state.transactions.clear()

    client.post("/explain/client", json=transaction(persist=True))

    assert client.get("/transactions").json()["total"] == 0


# ----------------------------------------- ответ провайдера как данные


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"choices": []},
        {"choices": [{"message": {}}]},
        {"choices": [{"message": {"content": "   "}}]},
        {"choices": [{"message": {"content": 42}}]},
    ],
)
def test_malformed_provider_answer_becomes_a_fallback(monkeypatch, body) -> None:
    """Чужой ответ — данные, а не гарантия формы."""
    def fake_post(url, *, json, headers, timeout):
        return httpx.Response(200, json=body, request=httpx.Request("POST", url))

    monkeypatch.setattr(llm_module.httpx, "post", fake_post)

    with pytest.raises(LlmUnavailableError):
        LlmClient(config()).complete("system", "user")


def test_timeout_is_reported_as_unavailable(monkeypatch) -> None:
    def fake_post(*args, **kwargs):
        raise httpx.ReadTimeout("too slow")

    monkeypatch.setattr(llm_module.httpx, "post", fake_post)

    with pytest.raises(LlmUnavailableError) as failure:
        LlmClient(config()).complete("system", "user")

    assert "не ответила" in failure.value.message


def test_generated_text_is_used_when_it_agrees(client, monkeypatch) -> None:
    """Счастливый путь: ответ модели не спорит с вердиктом и показывается."""
    written = "Мы приостановили операцию до вашего подтверждения. Деньги не списаны."

    def fake_post(url, *, json, headers, timeout):
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": written}}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(llm_module.httpx, "post", fake_post)
    settings = client.app.state.shin.settings
    monkeypatch.setattr(settings, "llm_api_key", Settings(llm_api_key=SECRET).llm_api_key)

    payload = client.post("/explain/client", json=transaction()).json()

    assert payload["decision"] == "CHALLENGE"
    assert payload["source"] == "llm"
    assert payload["text"] == written
    assert payload["model"] == settings.llm_model
    assert payload["fallback_reason"] is None


def test_build_facts_keeps_at_most_three_reasons(client) -> None:
    body = transaction()
    prediction = client.post("/predict", json=body).json()

    from app.schemas.prediction import PredictionResponse
    from app.schemas.transaction import TransactionRequest

    built = build_facts(TransactionRequest(**body), PredictionResponse(**prediction))

    assert len(built.reasons) <= 3


@pytest.mark.parametrize(
    ("language", "generated", "note"),
    [
        ("kk", "我们已暂停该笔交易，请您确认操作。", "иероглифы"),
        ("kk", "We have put the payment on hold until you confirm it.", "английский"),
        ("kk", "Мы приостановили операцию до вашего подтверждения.", "русский"),
        ("ru", "We have put the payment on hold until you confirm it.", "английский"),
    ],
)
def test_answer_in_the_wrong_language_falls_back(
    client, monkeypatch, language, generated, note
) -> None:
    """Сквозная проверка: ответ не на том языке клиенту не показывается.

    Текст, которого клиент не прочтёт, бесполезен ровно так же, как
    текст, спорящий с вердиктом. Запасной хотя бы читается.
    """
    def fake_post(url, *, json, headers, timeout):
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": generated}}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(llm_module.httpx, "post", fake_post)
    monkeypatch.setattr(
        client.app.state.shin.settings, "llm_api_key", Settings(llm_api_key=SECRET).llm_api_key
    )

    payload = client.post(f"/explain/client?language={language}", json=transaction()).json()

    assert payload["source"] == "fallback", note
    assert "не на запрошенном языке" in payload["fallback_reason"]
    assert payload["text"] != generated, "чужой язык всё-таки показан клиенту"
    assert payload["language"] == language


def test_answer_in_the_right_language_is_shown(client, monkeypatch) -> None:
    """Обратная сторона: правильный ответ обязан доходить до клиента.

    Без этой проверки защита, отвергающая всё подряд, выглядела бы
    работающей — ассистент молча заменился бы запасным текстом навсегда.
    """
    generated = "Операцияны сіз растағанша тоқтата тұрдық. Ақша есептен шығарылған жоқ."

    def fake_post(url, *, json, headers, timeout):
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": generated}}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(llm_module.httpx, "post", fake_post)
    monkeypatch.setattr(
        client.app.state.shin.settings, "llm_api_key", Settings(llm_api_key=SECRET).llm_api_key
    )

    payload = client.post("/explain/client?language=kk", json=transaction()).json()

    assert payload["source"] == "llm"
    assert payload["text"] == generated
    assert payload["fallback_reason"] is None
