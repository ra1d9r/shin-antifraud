"""Перечисления домена: решения, уровни риска, направления влияния факторов.

Вынесены отдельно, потому что используются во всех слоях — от Risk Engine
до frontend-контрактов.
"""

from __future__ import annotations

from enum import StrEnum


class Decision(StrEnum):
    """Решение системы по транзакции (ТЗ §1)."""

    APPROVE = "APPROVE"
    CHALLENGE = "CHALLENGE"
    BLOCK = "BLOCK"


class RiskLevel(StrEnum):
    """Уровень риска — человекочитаемая обёртка над Risk Score."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ImpactDirection(StrEnum):
    """Направление вклада признака в итоговый риск (XAI)."""

    INCREASES_RISK = "INCREASES_RISK"
    DECREASES_RISK = "DECREASES_RISK"


class Verdict(StrEnum):
    """Оценка аналитиком решения системы.

    Аналитик отвечает на вопрос «система была права?», а не «это фрод?»:
    он только что прочитал вердикт, ему остаётся согласиться или нет.
    Настоящая метка выводится из отметки и решения — см.
    `app.store.feedback.derive_actual_fraud`.
    """

    CORRECT = "CORRECT"
    INCORRECT = "INCORRECT"


class ScenarioKey(StrEnum):
    """Готовые сценарии hand-testing (ТЗ §9)."""

    NORMAL = "normal"
    NEW_DEVICE = "new_device"
    UNUSUAL_COUNTRY = "unusual_country"
    LARGE_AMOUNT = "large_amount"
    MULTIPLE_ANOMALIES = "multiple_anomalies"
    HIGH_FREQUENCY = "high_frequency"
