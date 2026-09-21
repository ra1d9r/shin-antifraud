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

Структура и подписи — по-русски, потому что их читает человек,
а не интеграция.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.schemas.prediction import PredictionResponse
from app.schemas.transaction import TransactionRequest

WIDTH = 72
HEAVY = "=" * WIDTH
LIGHT = "-" * WIDTH

#: Что решение означает на практике. Формулировки совпадают с таблицей
#: ТЗ §6 и описанием в Swagger. Полнота набора закреплена тестом:
#: новое решение без пояснения не должно проскочить молча.
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
    lines: list[str] = [
        HEAVY,
        f"  ОТЧЁТ ПО ОПЕРАЦИИ {response.transaction_id}",
        HEAVY,
        "",
        _field("Клиент", response.user_id),
        _field("Время операции", _moment(response.timestamp)),
        _field("Сумма", _money(request.amount)),
        _field("Мерчант", f"{request.merchant} ({request.country})"),
        _field("Устройство", request.device_id),
        _field("Возраст счёта", f"{request.account_age_days} дн."),
    ]

    # ------------------------------------------------------------ решение
    lines += _section(f"РЕШЕНИЕ: {response.decision.value}")
    lines += [
        _field("Risk Score", f"{response.risk_score} из 100 (уровень {response.risk_level.value})"),
        _field("Оценка модели", response.model_score),
        _field(
            "Подняли политики",
            f"да, с {response.model_score} до {response.risk_score}"
            if response.raised_by_rules
            else "нет",
        ),
        _field("Вероятность фрода", f"{response.probability:.4f}"),
        "",
        _field(
            "Пороги",
            f"APPROVE <= {response.thresholds.approve_max}"
            f" < CHALLENGE <= {response.thresholds.challenge_max} < BLOCK",
        ),
        "",
        f"  Что это значит: {response.decision.meaning}.",
    ]

    # ------------------------------------------------------------- почему
    lines += _section("ПОЧЕМУ")
    lines += [f"  {response.explanation.summary}", ""]

    # `reasons` содержит и политики, и факторы модели. Политики идут
    # отдельным блоком ниже, и без вычитания половина отчёта читалась бы
    # дважды подряд — причём формулировки политики и одноимённого признака
    # отличаются парой слов, и это выглядело бы как ошибка, а не как
    # два взгляда на одно.
    policy_reasons = set(response.explanation.policy_reasons)
    model_reasons = [
        reason for reason in response.explanation.reasons if reason not in policy_reasons
    ]

    if model_reasons:
        lines.append("  Что увидела модель:")
        lines += [f"    {index}. {reason}" for index, reason in enumerate(model_reasons, start=1)]
    else:
        # Пустой список — не сбой: у спокойной операции повышающих
        # факторов может не быть вовсе.
        lines.append("  Повышающих риск факторов модель не нашла.")

    lines.append("")
    if response.triggered_rules:
        lines.append("  Сработавшие политики:")
        lines += [
            f"    - {rule.key} (минимум {rule.min_score}): {rule.title}"
            for rule in response.triggered_rules
        ]
    else:
        lines.append("  Политики не срабатывали — оценка целиком от модели.")

    # -------------------------------------------------------- вклад признаков
    lines += _section("ВКЛАД ПРИЗНАКОВ")
    lines += [
        _field("Метод", response.explanation.method),
        _field("Единицы вклада", response.explanation.units),
    ]
    if response.explanation.units == "logit":
        lines.append(
            "  Вклад в логит базовой модели до калибровки; знак и порядок сохраняются."
        )
    lines += ["", f"  {'признак':<30}{'значение':>12}{'вклад':>11}  направление"]
    for factor in response.explanation.factors:
        direction = "повышает" if factor.contribution >= 0 else "понижает"
        lines.append(
            f"  {factor.feature:<30}{factor.display_value:>12}"
            f"{factor.contribution:>+11.4f}  {direction}"
        )

    # ------------------------------------------------------- чем посчитано
    lines += _section("ЧЕМ ПОСЧИТАНО")
    lines += [
        _field("Модель", f"{model_algorithm or 'неизвестно'} от {model_trained_at or 'неизвестно'}"),
        _field("Объяснение", response.explanation.method),
        _field("Время обработки", f"{response.processing_ms} мс"),
        _field("Отчёт сформирован", f"{_moment(moment)} UTC"),
        "",
        HEAVY,
    ]

    return "\n".join(lines) + "\n"
