"""Перечисления домена: решения, уровни риска, направления влияния факторов.

Вынесены отдельно, потому что используются во всех слоях — от Risk Engine
до frontend-контрактов.
"""

from __future__ import annotations

from enum import Enum


class Decision(str, Enum):
    """Решение системы по транзакции (ТЗ §1)."""

    APPROVE = "APPROVE"
    CHALLENGE = "CHALLENGE"
    BLOCK = "BLOCK"


class RiskLevel(str, Enum):
    """Уровень риска — человекочитаемая обёртка над Risk Score."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ImpactDirection(str, Enum):
    """Направление вклада признака в итоговый риск (XAI)."""

    INCREASES_RISK = "INCREASES_RISK"
    DECREASES_RISK = "DECREASES_RISK"


class ScenarioKey(str, Enum):
    """Готовые сценарии hand-testing (ТЗ §9)."""

    NORMAL = "normal"
    NEW_DEVICE = "new_device"
    UNUSUAL_COUNTRY = "unusual_country"
    LARGE_AMOUNT = "large_amount"
    MULTIPLE_ANOMALIES = "multiple_anomalies"
