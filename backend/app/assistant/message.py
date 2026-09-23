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
from app.features.geo import country_name
from app.i18n import DEFAULT_LANGUAGE, Language, Text
from app.schemas.enums import Decision
from app.schemas.prediction import PredictionResponse
from app.schemas.transaction import TransactionRequest

#: Сколько причин уходит в запрос. Брифинг §5.D говорит про три-пять
#: факторов, клиенту столько не нужно: за тремя пунктами он перестаёт
#: читать.
MAX_REASONS = 3

#: Подписи блока фактов на трёх языках.
#:
#: Блок уходит в двух направлениях сразу: в запрос к языковой модели
#: и на экран, в раздел «что уходит наружу». Оба читает человек —
#: первый через ответ модели, второй напрямую, — и русские подписи
#: при казахских значениях выглядели одинаково плохо в обоих.
#:
#: Модели перевод тоже на пользу: её просят ответить на нужном языке,
#: и факты на нём же избавляют её от перевода по ходу.
FACT_LABELS: dict[str, Text] = {
    "decision": Text(ru="Решение системы", kk="Жүйенің шешімі", en="System decision"),
    "score": Text(ru="Оценка риска", kk="Тәуекел бағасы", en="Risk score"),
    "outOf": Text(ru="из 100", kk="/ 100", en="of 100"),
    "amount": Text(ru="Сумма", kk="Сома", en="Amount"),
    "merchant": Text(ru="Получатель", kk="Алушы", en="Recipient"),
    "country": Text(ru="страна операции", kk="операция елі", en="transaction country"),
    "unusual": Text(
        ru="Что показалось системе необычным:",
        kk="Жүйеге не әдеттен тыс көрінді:",
        en="What looked unusual to the system:",
    ),
    "policies": Text(
        ru="Сработавшие политики безопасности:",
        kk="Іске қосылған қауіпсіздік саясаттары:",
        en="Security policies that fired:",
    ),
}


@dataclass(frozen=True, slots=True)
class DecisionFacts:
    """То, что система уже решила. Языковой модели остаётся это пересказать."""

    decision: Decision
    decision_meaning: str
    risk_score: int
    amount: float
    merchant: str
    # Название страны словом, а не код ISO: письмо клиенту
    # банка — не место для «NG». Разворачивается в `build_facts`,
    # где известен язык.
    country: str
    reasons: tuple[str, ...]
    policies: tuple[str, ...]
    #: Язык блока. Значения (страна, смысл решения, причины) уже
    #: переведены в `build_facts`; подписям нужен он же.
    language: Language = DEFAULT_LANGUAGE

    def as_prompt_block(self) -> str:
        """Факты одним блоком — то, что уходит в запрос.

        Собирается отдельным методом, чтобы тест мог проверить: в запрос
        не уходит ничего, кроме этих полей. Ни идентификатора клиента,
        ни номера операции, ни IP там нет — языковой модели они не нужны,
        а уезжают они на чужой сервер.
        """
        def label(key: str) -> str:
            return FACT_LABELS[key].get(self.language)

        lines = [
            f"{label('decision')}: {self.decision.value} ({self.decision_meaning})",
            f"{label('score')}: {self.risk_score} {label('outOf')}",
            f"{label('amount')}: {self.amount:.2f}",
            f"{label('merchant')}: {self.merchant}, {label('country')}: {self.country}",
        ]
        if self.reasons:
            lines.append(label("unusual"))
            lines += [f"- {reason}" for reason in self.reasons]
        if self.policies:
            lines.append(label("policies"))
            lines += [f"- {policy}" for policy in self.policies]
        return "\n".join(lines)


def build_facts(
    request: TransactionRequest,
    response: PredictionResponse,
    language: Language = DEFAULT_LANGUAGE,
) -> DecisionFacts:
    """Собрать факты решения для ассистента.

    Язык нужен здесь, а не в промпте: страна приходит кодом ISO,
    а модели нельзя поручить его развернуть — её же инструкция
    запрещает сообщать факты, которых нет во входных данных.
    """
    reasons = tuple(response.explanation.reasons[:MAX_REASONS])
    policies = tuple(rule.title for rule in response.triggered_rules)
    return DecisionFacts(
        decision=response.decision,
        decision_meaning=response.decision.meaning_in(language),
        risk_score=response.risk_score,
        amount=request.amount,
        merchant=request.merchant,
        country=country_name(request.country, language),
        reasons=reasons,
        policies=policies,
        language=language,
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


#: Буквы, которые есть в казахском и которых нет в русском. Ими эти два
#: языка и различаются: обычный казахский абзац содержит их в изобилии
#: (в наших собственных текстах — по семь-восемь разных на абзац),
#: русский — ни одной.
KAZAKH_LETTERS = frozenset("әғқңөұүһі")

#: Письменности, появление которых в ответе означает, что модель ушла
#: не туда. Китайский — не гипотеза: модели, которых просят писать
#: по-казахски, иногда отвечают на языке, на котором их учили больше.
FOREIGN_SCRIPTS = (
    (0x4E00, 0x9FFF),  # китайские иероглифы
    (0x3040, 0x30FF),  # японские каны
    (0xAC00, 0xD7AF),  # корейский хангыль
    (0x0600, 0x06FF),  # арабица
    (0x0590, 0x05FF),  # иврит
    (0x0E00, 0x0E7F),  # тайский
)

#: Какая доля букв должна принадлежать ожидаемой письменности.
#: Не 100%: в тексте законно встречается название мерчанта латиницей
#: («CryptoExchange»), и требовать чистоты значило бы отвергать
#: правильные ответы. В наших текстах доля ожидаемой письменности
#: не опускается ниже 0.85, так что запас есть.
MIN_SCRIPT_SHARE = 0.6


def _is_cyrillic(char: str) -> bool:
    return "Ѐ" <= char <= "ӿ"


def written_in(text: str, language: Language) -> bool:
    """Похож ли текст на написанный на запрошенном языке.

    Проверка грубая и намеренно такая: определять язык по-настоящему
    значило бы тащить в проект ещё одну модель ради одного случая.
    Ловит она то, что действительно случается, — уход модели в другую
    письменность целиком.

    Три правила:

    1. Чужая письменность запрещена совсем. Иероглифов в ответе клиенту
       казахстанского банка быть не может ни при каких обстоятельствах.
    2. Ожидаемая письменность должна преобладать: кириллица для русского
       и казахского, латиница для английского.
    3. Казахский дополнительно обязан содержать хотя бы одну букву,
       которой нет в русском. Без этого правила ответ по-русски на
       просьбу писать по-казахски прошёл бы незамеченным — а это самая
       вероятная из ошибок, потому что казахского в обучающих данных
       меньше.

    Пустой текст не проходит: показывать клиенту нечего.
    """
    if not text.strip():
        return False

    for char in text:
        code = ord(char)
        if any(low <= code <= high for low, high in FOREIGN_SCRIPTS):
            return False

    letters = [char for char in text if char.isalpha()]
    if not letters:
        return False

    cyrillic = sum(1 for char in letters if _is_cyrillic(char))
    share = cyrillic / len(letters) if language != "en" else 1 - cyrillic / len(letters)
    if share < MIN_SCRIPT_SHARE:
        return False

    if language == "kk":
        return bool(KAZAKH_LETTERS & set(text.lower()))

    return True


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
