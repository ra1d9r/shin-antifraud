"""Risk Engine: вероятность -> Risk Score -> решение (ТЗ §6).

Слой намеренно ничего не знает ни про HTTP, ни про то, какая модель выдала
вероятность. На вход — число от 0 до 1 и вектор признаков, на выход — оценка,
уровень риска, решение и перечень сработавших политик.

Пороги приходят объектом `RiskThresholds`, а не читаются из глобальной
конфигурации внутри. Это нужно для страницы Business Cost (ТЗ §10), где один
и тот же поток транзакций пересчитывается при разных порогах: достаточно
создать движок с другими порогами, ничего не меняя в окружении.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field

from app.config.settings import Settings
from app.core.exceptions import InvalidConfigurationError
from app.risk_engine.rules import Rule, TriggeredRule, build_rules, evaluate_rules, minimum_score
from app.schemas.enums import Decision, RiskLevel

FeatureMap = Mapping[str, float]

MIN_SCORE = 0
MAX_SCORE = 100


@dataclass(frozen=True, slots=True)
class RiskThresholds:
    """Границы принятия решений."""

    approve_max: int
    challenge_max: int
    critical_min: int

    def __post_init__(self) -> None:
        if not MIN_SCORE <= self.approve_max < self.challenge_max <= MAX_SCORE:
            raise InvalidConfigurationError(
                "Пороги должны возрастать в пределах 0..100: "
                f"approve_max={self.approve_max}, challenge_max={self.challenge_max}"
            )
        if not self.challenge_max < self.critical_min <= MAX_SCORE:
            raise InvalidConfigurationError(
                f"critical_min ({self.critical_min}) должен быть больше "
                f"challenge_max ({self.challenge_max}) и не больше 100"
            )

    @classmethod
    def from_settings(cls, settings: Settings) -> RiskThresholds:
        return cls(
            approve_max=settings.risk_approve_max,
            challenge_max=settings.risk_challenge_max,
            critical_min=settings.risk_critical_min,
        )

    def to_dict(self) -> dict:
        return {
            "approve_max": self.approve_max,
            "challenge_max": self.challenge_max,
            "critical_min": self.critical_min,
        }


@dataclass(frozen=True, slots=True)
class RiskAssessment:
    """Результат работы Risk Engine.

    `model_score` и `risk_score` разделены намеренно: интерфейс должен
    показывать, что именно подняло оценку — модель или политика. Без этого
    объяснение решения было бы неполным.
    """

    probability: float
    model_score: int
    risk_score: int
    decision: Decision
    risk_level: RiskLevel
    thresholds: RiskThresholds
    triggered_rules: tuple[TriggeredRule, ...] = field(default_factory=tuple)

    @property
    def raised_by_rules(self) -> bool:
        """Подняли ли политики оценку выше того, что дала модель."""
        return self.risk_score > self.model_score

    def to_dict(self) -> dict:
        return {
            "probability": round(self.probability, 6),
            "model_score": self.model_score,
            "risk_score": self.risk_score,
            "decision": self.decision.value,
            "risk_level": self.risk_level.value,
            "raised_by_rules": self.raised_by_rules,
            "triggered_rules": [rule.to_dict() for rule in self.triggered_rules],
            "thresholds": self.thresholds.to_dict(),
        }


def probability_to_score(probability: float) -> int:
    """Вероятность 0..1 -> Risk Score 0..100.

    Используется арифметическое округление, а не встроенное `round`:
    `round` в Python применяет банковское округление (`round(2.5) == 2`),
    из-за чего оценка на границе порога вела бы себя неочевидно.
    """
    if math.isnan(probability):
        raise InvalidConfigurationError("Вероятность не может быть NaN")

    clamped = min(max(probability, 0.0), 1.0)
    return math.floor(clamped * 100 + 0.5)


class RiskEngine:
    """Переводит вероятность модели в решение по транзакции."""

    def __init__(
        self,
        thresholds: RiskThresholds,
        rules: tuple[Rule, ...] = (),
        rules_enabled: bool = True,
    ) -> None:
        self.thresholds = thresholds
        self.rules = rules
        self.rules_enabled = rules_enabled

    @classmethod
    def from_settings(cls, settings: Settings) -> RiskEngine:
        return cls(
            thresholds=RiskThresholds.from_settings(settings),
            rules=build_rules(settings),
            rules_enabled=settings.rules_enabled,
        )

    def with_thresholds(self, thresholds: RiskThresholds) -> RiskEngine:
        """Копия движка с другими порогами — для перебора в Business Cost."""
        return RiskEngine(
            thresholds=thresholds,
            rules=self.rules,
            rules_enabled=self.rules_enabled,
        )

    # ------------------------------------------------------------- решения

    def decide(self, risk_score: int) -> Decision:
        """Решение по итоговой оценке (ТЗ §6)."""
        if risk_score <= self.thresholds.approve_max:
            return Decision.APPROVE
        if risk_score <= self.thresholds.challenge_max:
            return Decision.CHALLENGE
        return Decision.BLOCK

    def level(self, risk_score: int) -> RiskLevel:
        """Уровень риска — человекочитаемая шкала поверх оценки."""
        if risk_score >= self.thresholds.critical_min:
            return RiskLevel.CRITICAL
        if risk_score > self.thresholds.challenge_max:
            return RiskLevel.HIGH
        if risk_score > self.thresholds.approve_max:
            return RiskLevel.MEDIUM
        return RiskLevel.LOW

    # ------------------------------------------------------------- оценка

    def assess(self, probability: float, features: FeatureMap | None = None) -> RiskAssessment:
        """Полная оценка транзакции.

        Args:
            probability: вероятность фрода от модели, 0..1.
            features: вектор признаков — нужен только правилам.
        """
        model_score = probability_to_score(probability)

        triggered: tuple[TriggeredRule, ...] = ()
        if self.rules_enabled and self.rules and features is not None:
            triggered = evaluate_rules(self.rules, features)

        # Правила только поднимают оценку и никогда не снижают.
        risk_score = min(MAX_SCORE, max(model_score, minimum_score(triggered)))

        return RiskAssessment(
            probability=float(min(max(probability, 0.0), 1.0)),
            model_score=model_score,
            risk_score=risk_score,
            decision=self.decide(risk_score),
            risk_level=self.level(risk_score),
            thresholds=self.thresholds,
            triggered_rules=triggered,
        )
