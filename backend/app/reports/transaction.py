"""Отчёт по одной операции — текстом, для человека.

## Зачем, если есть JSON

`POST /predict` отдаёт всё то же самое, и в интерфейсе оно разложено
по панелям. Но обе формы предполагают, что читатель сидит перед
системой Shin.

Аналитик, разобравший операцию, живёт не там. Он пишет в тикет, отвечает
клиентской службе, прикладывает обоснование к решению по обращению.
Вставить туда JSON нельзя, а пересказывать своими словами — значит
каждый раз заново придумывать формулировки и рано или поздно написать
не то, что система решила на самом деле.

Отчёт закрывает именно этот разрыв: одна страница, которую можно
скопировать целиком.

## Почему текст, а не PDF или HTML

Текст вставляется куда угодно — в тикет, в почту, в мессенджер,
в поле «комментарий» внутренней системы. PDF пришлось бы открывать,
HTML — рендерить. Ни то ни другое не помогает человеку, которому нужно
объяснить одно решение одному коллеге.

## Почему причины остаются на английском

Формулировки причин приходят из XAI как есть. ТЗ §7 задаёт их
по-английски, и это официальная формулировка системы. Перевести их
здесь значило бы завести вторую версию того же утверждения: в API одна,
в отчёте другая, и при расхождении не понять, какая настоящая.

Структура и подписи переводятся параметром `?language=`: отчёт читает
человек, и язык у него тот же, на котором он работает.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.i18n import DEFAULT_LANGUAGE, Language, Text
from app.schemas.prediction import PredictionResponse
from app.schemas.transaction import TransactionRequest

WIDTH = 72
HEAVY = "=" * WIDTH
LIGHT = "-" * WIDTH

#: Подписи отчёта на трёх языках (брифинг §6).
#:
#: Отчёт вставляют в тикет и в переписку с клиентской службой, и язык
#: там тот же, на котором работает аналитик. Пока подписи были русскими,
#: отчёт оставался единственным местом, где `?language=` ничего не менял.
#:
#: Формулировки причин и названия политик сюда не входят: они приходят
#: из XAI по-английски, так их задаёт ТЗ §7, и это официальная
#: формулировка системы. Перевести их здесь значило бы завести вторую
#: версию того же утверждения — в API одна, в отчёте другая.
REPORT_TEXT: dict[str, Text] = {
    "title": Text(ru="ОТЧЁТ ПО ОПЕРАЦИИ", kk="ОПЕРАЦИЯ БОЙЫНША ЕСЕП", en="TRANSACTION REPORT"),
    "client": Text(ru="Клиент", kk="Клиент", en="Client"),
    "moment": Text(ru="Время операции", kk="Операция уақыты", en="Transaction time"),
    "amount": Text(ru="Сумма", kk="Сома", en="Amount"),
    "merchant": Text(ru="Мерчант", kk="Мерчант", en="Merchant"),
    "device": Text(ru="Устройство", kk="Құрылғы", en="Device"),
    "accountAge": Text(ru="Возраст счёта", kk="Шот жасы", en="Account age"),
    "days": Text(ru="дн.", kk="күн", en="days"),
    "decision": Text(ru="РЕШЕНИЕ", kk="ШЕШІМ", en="DECISION"),
    "outOf": Text(ru="из 100 (уровень", kk="/ 100 (деңгей", en="of 100 (level"),
    "modelScore": Text(ru="Оценка модели", kk="Модель бағасы", en="Model score"),
    "raisedByRules": Text(ru="Подняли политики", kk="Саясат көтерді", en="Raised by policies"),
    "raisedFromTo": Text(
        ru="да, с {before} до {after}",
        kk="иә, {before} -> {after}",
        en="yes, {before} -> {after}",
    ),
    "no": Text(ru="нет", kk="жоқ", en="no"),
    "probability": Text(ru="Вероятность фрода", kk="Алаяқтық ықтималдығы", en="Fraud probability"),
    "thresholds": Text(ru="Пороги", kk="Шектер", en="Thresholds"),
    "meansThat": Text(ru="Что это значит", kk="Бұл нені білдіреді", en="What this means"),
    "why": Text(ru="ПОЧЕМУ", kk="НЕЛІКТЕН", en="WHY"),
    "modelSaw": Text(ru="Что увидела модель:", kk="Модель нені көрді:", en="What the model saw:"),
    "modelSawNothing": Text(
        ru="Повышающих риск факторов модель не нашла.",
        kk="Модель тәуекелді арттыратын белгі таппады.",
        en="The model found no risk-increasing factors.",
    ),
    "policiesFired": Text(
        ru="Сработавшие политики:",
        kk="Іске қосылған саясаттар:",
        en="Policies that fired:",
    ),
    "policiesQuiet": Text(
        ru="Политики не срабатывали — оценка целиком от модели.",
        kk="Саясаттар іске қосылмады — баға толығымен модельден.",
        en="No policies fired — the score comes entirely from the model.",
    ),
    "minimum": Text(ru="минимум", kk="кемінде", en="min"),
    "contributions": Text(ru="ВКЛАД ПРИЗНАКОВ", kk="БЕЛГІЛЕРДІҢ ҮЛЕСІ", en="FEATURE CONTRIBUTIONS"),
    "method": Text(ru="Метод", kk="Әдіс", en="Method"),
    "units": Text(ru="Единицы вклада", kk="Үлес бірліктері", en="Contribution units"),
    "logitNote": Text(
        ru="Вклад в логит базовой модели до калибровки; знак и порядок сохраняются.",
        kk="Калибрлеуге дейінгі базалық модель логитіне үлес; таңба мен реті сақталады.",
        en="Contribution to the base model logit before calibration; sign and order are preserved.",
    ),
    "colFeature": Text(ru="признак", kk="белгі", en="feature"),
    "colValue": Text(ru="значение", kk="мәні", en="value"),
    "colContribution": Text(ru="вклад", kk="үлесі", en="contribution"),
    "colDirection": Text(ru="направление", kk="бағыты", en="direction"),
    "raises": Text(ru="повышает", kk="арттырады", en="raises"),
    "lowers": Text(ru="понижает", kk="төмендетеді", en="lowers"),
    "computedBy": Text(ru="ЧЕМ ПОСЧИТАНО", kk="НЕМЕН ЕСЕПТЕЛДІ", en="HOW IT WAS COMPUTED"),
    "model": Text(ru="Модель", kk="Модель", en="Model"),
    "explanation": Text(ru="Объяснение", kk="Түсіндірме", en="Explanation"),
    "processingTime": Text(ru="Время обработки", kk="Өңдеу уақыты", en="Processing time"),
    "generatedAt": Text(ru="Отчёт сформирован", kk="Есеп жасалды", en="Report generated"),
    "unknown": Text(ru="неизвестно", kk="белгісіз", en="unknown"),
    "from": Text(ru="от", kk="—", en="of"),
    "ms": Text(ru="мс", kk="мс", en="ms"),
}

def _money(value: float) -> str:
    """Сумма с разделением разрядов. Пробел, а не запятая, — как в отчётах скриптов."""
    return f"{value:,.2f}".replace(",", " ")


def _moment(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _section(title: str) -> list[str]:
    return ["", LIGHT, f"  {title}", LIGHT, ""]


def _field(label: str, value: object) -> str:
    return f"  {label:<20}: {value}"


def render_transaction_report(
    request: TransactionRequest,
    response: PredictionResponse,
    *,
    model_algorithm: str | None = None,
    model_trained_at: str | None = None,
    generated_at: datetime | None = None,
    language: Language = DEFAULT_LANGUAGE,
) -> str:
    """Собрать отчёт по операции.

    Args:
        request: что прислали на анализ — суммы и мерчанта в ответе нет.
        response: что система решила и почему.
        model_algorithm: чем считали. Нужно, чтобы отчёт годился в дело:
            через месяц модель будет другой, и без метки непонятно,
            на чём основано решение.
        generated_at: время формирования. Задаётся снаружи в тестах,
            иначе отчёт нельзя было бы сравнить с эталоном.
    """
    moment = generated_at or datetime.now(UTC).replace(microsecond=0)

    def label(key: str) -> str:
        return REPORT_TEXT[key].get(language)

    unknown = label("unknown")
    lines: list[str] = [
        HEAVY,
        f"  {label('title')} {response.transaction_id}",
        HEAVY,
        "",
        _field(label("client"), response.user_id),
        _field(label("moment"), _moment(response.timestamp)),
        _field(label("amount"), _money(request.amount)),
        _field(label("merchant"), f"{request.merchant} ({request.country})"),
        _field(label("device"), request.device_id),
        _field(label("accountAge"), f"{request.account_age_days} {label('days')}"),
    ]

    # ------------------------------------------------------------ решение
    lines += _section(f"{label('decision')}: {response.decision.value}")
    lines += [
        _field(
            "Risk Score",
            f"{response.risk_score} {label('outOf')} {response.risk_level.value})",
        ),
        _field(label("modelScore"), response.model_score),
        _field(
            label("raisedByRules"),
            REPORT_TEXT["raisedFromTo"]
            .get(language)
            .format(before=response.model_score, after=response.risk_score)
            if response.raised_by_rules
            else label("no"),
        ),
        _field(label("probability"), f"{response.probability:.4f}"),
        "",
        _field(
            label("thresholds"),
            f"APPROVE <= {response.thresholds.approve_max}"
            f" < CHALLENGE <= {response.thresholds.challenge_max} < BLOCK",
        ),
        "",
        f"  {label('meansThat')}: {response.decision.meaning_in(language)}.",
    ]

    # ------------------------------------------------------------- почему
    lines += _section(label("why"))
    lines += [f"  {response.explanation.summary}", ""]

    # Список причин от модели берётся готовым, а не вычитается здесь
    # из общего: правило «что считать причиной» живёт в одном месте
    # (см. `Explanation.model_reasons`), и вторая его копия однажды
    # разошлась бы с первой.
    model_reasons = response.explanation.model_reasons

    if model_reasons:
        lines.append(f"  {label('modelSaw')}")
        lines += [f"    {index}. {reason}" for index, reason in enumerate(model_reasons, start=1)]
    else:
        # Пустой список — не сбой: у спокойной операции повышающих
        # факторов может не быть вовсе.
        lines.append(f"  {label('modelSawNothing')}")

    lines.append("")
    if response.triggered_rules:
        lines.append(f"  {label('policiesFired')}")
        lines += [
            f"    - {rule.key} ({label('minimum')} {rule.min_score}): {rule.title}"
            for rule in response.triggered_rules
        ]
    else:
        lines.append(f"  {label('policiesQuiet')}")

    # -------------------------------------------------------- вклад признаков
    lines += _section(label("contributions"))
    lines += [
        _field(label("method"), response.explanation.method),
        _field(label("units"), response.explanation.units),
    ]
    if response.explanation.units == "logit":
        lines.append(f"  {label('logitNote')}")
    lines += [
        "",
        f"  {label('colFeature'):<30}{label('colValue'):>12}"
        f"{label('colContribution'):>11}  {label('colDirection')}",
    ]
    for factor in response.explanation.factors:
        direction = label("raises") if factor.contribution >= 0 else label("lowers")
        lines.append(
            f"  {factor.feature:<30}{factor.display_value:>12}"
            f"{factor.contribution:>+11.4f}  {direction}"
        )

    # ------------------------------------------------------- чем посчитано
    lines += _section(label("computedBy"))
    lines += [
        _field(
            label("model"),
            f"{model_algorithm or unknown} {label('from')} {model_trained_at or unknown}",
        ),
        _field(label("explanation"), response.explanation.method),
        _field(label("processingTime"), f"{response.processing_ms} {label('ms')}"),
        _field(label("generatedAt"), f"{_moment(moment)} UTC"),
        "",
        HEAVY,
    ]

    return "\n".join(lines) + "\n"
