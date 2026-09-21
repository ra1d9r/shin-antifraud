"""Перечисления домена: решения, уровни риска, направления влияния факторов.

Вынесены отдельно, потому что используются во всех слоях — от Risk Engine
до frontend-контрактов.
"""

from __future__ import annotations

from enum import StrEnum

from app.i18n import DEFAULT_LANGUAGE, Language, Text


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

        Свойство отдаёт русский вариант — язык проекта. Там, где язык
        спрошен, зовут `meaning_in`.
        """
        return self.meaning_in(DEFAULT_LANGUAGE)

    def meaning_in(self, language: Language) -> str:
        """То же пояснение на запрошенном языке (брифинг §6)."""
        return _DECISION_MEANING[self].get(language)


_DECISION_MEANING: dict[Decision, Text] = {
    Decision.APPROVE: Text(
        ru="операция проходит, клиент ничего не заметил",
        kk="операция өтеді, клиент ештеңе байқамайды",
        en="the transaction goes through; the client notices nothing",
    ),
    Decision.CHALLENGE: Text(
        ru="нужно подтверждение владельца — 2FA или биометрия",
        kk="иесінің растауы қажет — 2FA немесе биометрия",
        en="the owner must confirm — 2FA or biometrics",
    ),
    Decision.BLOCK: Text(
        ru="операция отклонена",
        kk="операция қабылданбады",
        en="the transaction is declined",
    ),
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
