"""Перевод технического признака в формулировку для человека (ТЗ §7).

Реестр признаков (`features/definitions.py`) хранит два шаблона для каждого
признака: как сказать, когда он повышает риск, и как — когда понижает.
Этот модуль подставляет в шаблон фактическое значение и выбирает нужный
вариант по знаку вклада.

Формулировки на английском — так они приведены в примере ТЗ §7 и так их
показывает Dashboard.
"""

from __future__ import annotations

from app.features.definitions import FeatureSpec, get_spec, has_spec
from app.schemas.enums import ImpactDirection

# Вклад меньше этого считается шумом и в объяснение не попадает.
NEGLIGIBLE_CONTRIBUTION = 1e-6


def direction_of(contribution: float) -> ImpactDirection:
    """Повышает вклад риск или понижает."""
    return (
        ImpactDirection.INCREASES_RISK
        if contribution > 0
        else ImpactDirection.DECREASES_RISK
    )


def describe(feature: str, value: float, contribution: float) -> str:
    """Человекочитаемая причина для одного признака.

    Для неизвестного признака возвращается техническое имя со значением —
    это лучше, чем падение объяснения из-за рассинхронизации реестра.
    """
    if not has_spec(feature):
        return f"{feature} = {value:.2f}"

    spec = get_spec(feature)
    template = _pick_template(spec, contribution)
    formatted = spec.format_value(value)
    return template.replace("{value}", formatted)


def _pick_template(spec: FeatureSpec, contribution: float) -> str:
    """Выбрать шаблон по знаку вклада.

    Если для понижающего вклада шаблона нет, используется повышающий:
    признак всё равно нужно назвать, а направление показывается отдельным
    полем и знаком величины.
    """
    if contribution < 0 and spec.reason_low:
        return spec.reason_low
    return spec.reason_high


def is_negligible(contribution: float) -> bool:
    """Вклад настолько мал, что о нём не стоит рассказывать."""
    return abs(contribution) < NEGLIGIBLE_CONTRIBUTION


def summarise(risk_score: int, decision: str, factor_count: int, rule_count: int) -> str:
    """Одна фраза, объясняющая решение целиком."""
    parts = [f"Risk score {risk_score}/100 resulted in {decision}."]

    if rule_count and factor_count:
        parts.append(
            f"{rule_count} policy rule(s) applied on top of the model, "
            f"and {factor_count} model factor(s) contributed to the score."
        )
    elif rule_count:
        parts.append(f"The score was set by {rule_count} policy rule(s).")
    elif factor_count:
        parts.append(f"The score is driven by {factor_count} model factor(s).")
    else:
        parts.append("No individual factor stands out for this transaction.")

    return " ".join(parts)
