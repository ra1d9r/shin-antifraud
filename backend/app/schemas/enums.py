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

    @property
    def meaning(self) -> str:
        """Что решение означает для клиента.

        Живёт при самом решении, а не там, где показывается. Сначала
        формулировки были в двух местах — в текстовом отчёте и в вердикте
        интерфейса, — и уже разошлись: отчёт говорил «нужна дополнительная
        проверка или 2FA», интерфейс «нужно подтверждение владельца».
        Система описывала одно своё решение двумя разными фразами.

        Формулировка CHALLENGE следует брифингу: §4.3 называет действие
        «Challenge/2FA (Доп. проверка)», §10.3 — «запрос на биометрическую
        верификацию (2FA)».
        """
        return _DECISION_MEANING[self]


_DECISION_MEANING: dict[Decision, str] = {
    Decision.APPROVE: "операция проходит, клиент ничего не заметил",
    Decision.CHALLENGE: "нужно подтверждение владельца — 2FA или биометрия",
    Decision.BLOCK: "операция отклонена",
}


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
