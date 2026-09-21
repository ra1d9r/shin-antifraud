"""Ответ клиенту, почему у него попросили подтверждение (брифинг §6).

Брифинг §6: «LLM-Ассистент Риск-аналитика: генерация естественного
ответа для клиента, объясняющего, почему потребовалось
2FA-подтверждение».

## Что здесь делает языковая модель и чего не делает

Решение принято до неё и без неё: вероятность даёт обученная модель,
оценку и вердикт — Risk Engine, причины — SHAP. Языковая модель получает
уже готовые факты и только превращает их в фразу, которую не стыдно
показать человеку.

Это принципиальное разделение, а не осторожность. Дай модели решать —
и система превратится в обёртку над чужим API: вердикт нельзя будет
ни воспроизвести, ни объяснить, ни проверить тестом. Здесь наоборот:
выключите ассистента, и система продолжит работать ровно так же,
изменится только формулировка текста.

## Почему ответ проверяется после генерации

Языковая модель может написать «операция отклонена» там, где система
всего лишь попросила подтверждение. Для клиента это разные вещи:
в первом случае деньги не ушли, во втором — уйдут после подтверждения.
Поэтому текст сверяется с вердиктом, и при расхождении показывается
запасной.

Проверка простая — по словам противоположного вердикта, — и полноты
не гарантирует. Она ловит ровно то, что ломает смысл, и не пытается
изображать понимание текста.

## Почему есть детерминированный запасной текст

Без ключа, при недоступном API и при таймауте клиент всё равно обязан
получить ответ. Запасной текст собирается из тех же фактов, что ушли бы
в запрос, поэтому говорит то же самое — только суше.

В ответе всегда видно, кто написал текст: `source` равен `llm` или
`fallback`. Выдавать шаблон за работу языковой модели значило бы
заявить функциональность, которой в этот момент нет.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.assistant import phrases
from app.assistant.phrases import DEFAULT_LANGUAGE, Language
from app.schemas.enums import Decision
from app.schemas.prediction import PredictionResponse
from app.schemas.transaction import TransactionRequest

#: Сколько причин уходит в запрос. Брифинг §5.D говорит про три-пять
#: факторов, клиенту столько не нужно: за тремя пунктами он перестаёт
#: читать.
MAX_REASONS = 3

@dataclass(frozen=True, slots=True)
class DecisionFacts:
    """То, что система уже решила. Языковой модели остаётся это пересказать."""

    decision: Decision
    decision_meaning: str
    risk_score: int
    amount: float
    merchant: str
    country: str
    reasons: tuple[str, ...]
    policies: tuple[str, ...]

    def as_prompt_block(self) -> str:
        """Факты одним блоком — то, что уходит в запрос.

        Собирается отдельным методом, чтобы тест мог проверить: в запрос
        не уходит ничего, кроме этих полей. Ни идентификатора клиента,
        ни номера операции, ни IP там нет — языковой модели они не нужны,
        а уезжают они на чужой сервер.
        """
        lines = [
            f"Решение системы: {self.decision.value} ({self.decision_meaning})",
            f"Оценка риска: {self.risk_score} из 100",
            f"Сумма: {self.amount:.2f}",
            f"Получатель: {self.merchant}, страна операции: {self.country}",
        ]
        if self.reasons:
            lines.append("Что показалось системе необычным:")
            lines += [f"- {reason}" for reason in self.reasons]
        if self.policies:
            lines.append("Сработавшие политики безопасности:")
            lines += [f"- {policy}" for policy in self.policies]
        return "\n".join(lines)


def build_facts(request: TransactionRequest, response: PredictionResponse) -> DecisionFacts:
    """Собрать факты решения для ассистента."""
    reasons = tuple(response.explanation.reasons[:MAX_REASONS])
    policies = tuple(rule.title for rule in response.triggered_rules)
    return DecisionFacts(
        decision=response.decision,
        decision_meaning=response.decision.meaning,
        risk_score=response.risk_score,
        amount=request.amount,
        merchant=request.merchant,
        country=request.country,
        reasons=reasons,
        policies=policies,
    )


def fallback_text(facts: DecisionFacts, language: Language = DEFAULT_LANGUAGE) -> str:
    """Тот же ответ, собранный без языковой модели.

    Говорит то же самое, что сказал бы ассистент, только суше.

    Причины **не перечисляются дословно**, хотя они есть. XAI формулирует
    их по-английски и для аналитика: «Amount deviates 50.0 standard
    deviations from the user's usual spending». Вставить такое в письмо
    клиенту банк не может, а перевести здесь значило бы завести вторую
    версию каждой формулировки, которая однажды разойдётся с первой.

    Поэтому запасной текст честно говорит, сколько сигналов сработало,
    и не притворяется подробным объяснением. Подробное — это работа
    языковой модели, ради которой она и позвана; сами причины видны
    аналитику в поле `facts` ответа и в текстовом отчёте.
    """
    return phrases.compose(
        facts.decision,
        language,
        amount=facts.amount,
        merchant=facts.merchant,
        reason_count=len(facts.reasons),
    )


def contradicts(text: str, decision: Decision) -> bool:
    """Говорит ли текст про другое решение, чем принято.

    Для клиента «операция отклонена» и «подтвердите операцию» —
    совершенно разные новости, и перепутать их хуже, чем не написать
    ничего. Поэтому текст, противоречащий вердикту, не показывается.

    Слова проверяются на всех трёх языках сразу: модель, которую
    попросили писать по-казахски, может ответить по-русски, и проверка
    обязана поймать противоречие в любом случае.
    """
    lowered = text.lower()
    return any(word in lowered for word in phrases.FORBIDDEN_WORDS[decision])


def needs_assistant(decision: Decision) -> bool:
    """Стоит ли вообще звать языковую модель.

    Одобренная операция клиента не беспокоит, объяснять ему нечего —
    и платить за вызов не за что. Запасной текст такой случай закрывает.
    """
    return decision is not Decision.APPROVE
