"""Объяснение решения (ТЗ §7).

Собирает воедино две независимые причины, по которым транзакция получила
свою оценку:

1. **вклады признаков модели** — почему так посчитала ML-модель;
2. **сработавшие политики** Risk Engine — что подняло оценку сверх модели.

Показывать только первое было бы неполно и местами прямо обманчиво: в
сценарии «новое устройство» модель даёт 1 балл, а итоговые 35 полностью
заслуга правила. Объяснение обязано это показывать.

Количество факторов ограничено требованием ТЗ §7: не меньше трёх и не
больше пяти.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.core.exceptions import ExplanationError
from app.core.logging import get_logger
from app.features.definitions import FEATURE_NAMES, get_spec, has_spec
from app.i18n import DEFAULT_LANGUAGE, Language, Text
from app.risk_engine.engine import RiskAssessment
from app.schemas.enums import ImpactDirection
from app.xai import narrator
from app.xai.contributions import ContributionEngine, build_contribution_engine

logger = get_logger("shin.xai.explainer")

MIN_FACTORS = 3
MAX_FACTORS = 5


@dataclass(frozen=True, slots=True)
class RiskFactor:
    """Один фактор риска в объяснении."""

    feature: str
    value: float
    display_value: str
    contribution: float
    direction: ImpactDirection
    reason: str
    # Описание признака на трёх языках. Строкой становится на границе
    # API, где известен запрошенный язык: внутри держать одну из трёх
    # версий значило бы выбирать язык там, где его ещё не спросили.
    description: Text

    def to_dict(self, language: Language = DEFAULT_LANGUAGE) -> dict:
        return {
            "feature": self.feature,
            "value": round(self.value, 4),
            "display_value": self.display_value,
            "contribution": round(self.contribution, 6),
            "direction": self.direction.value,
            "reason": self.reason,
            "description": self.description.get(language),
        }


@dataclass(frozen=True, slots=True)
class Explanation:
    """Полное объяснение решения по транзакции."""

    method: str
    units: str
    base_value: float
    factors: tuple[RiskFactor, ...]
    policy_reasons: tuple[str, ...] = field(default_factory=tuple)
    summary: str = ""

    @property
    def model_reasons(self) -> tuple[str, ...]:
        """Причины от модели — без политик.

        Отдаётся отдельным полем, потому что интерфейс показывает
        политики и факторы разными списками. Пока поля не было, он
        фильтровал факторы сам — то есть держал вторую копию правила
        «что считать причиной», а ТЗ §11 запрещает клиенту вычислять.
        Копия немедленно разошлась с оригиналом: backend отсеивал шум,
        а экран его показывал.

        Мало быть положительным — надо ещё что-то значить. Признак,
        сдвинувший логит на пять процентов базы, риск формально повышал,
        но причиной решения не был (см. `narrator.is_meaningful`).
        """
        return tuple(
            factor.reason
            for factor in self.factors
            if factor.direction is ImpactDirection.INCREASES_RISK
            and narrator.is_meaningful(factor.contribution, self.base_value)
        )

    @property
    def reasons(self) -> tuple[str, ...]:
        """Плоский список причин: сначала политики, затем факторы модели.

        Политики идут первыми потому, что они детерминированы и обычно
        и определяют решение, тогда как вклад модели объясняет оттенки.

        Повторы убираются: формулировка политики и формулировка признака
        могут совпасть дословно (например, «Transaction from a high-risk
        country» приходит и от правила, и от признака `is_high_risk_country`),
        а одна и та же фраза дважды в списке выглядит как ошибка.
        """
        seen: set[str] = set()
        unique: list[str] = []
        for reason in (*self.policy_reasons, *self.model_reasons):
            key = reason.strip().lower()
            if key not in seen:
                seen.add(key)
                unique.append(reason)
        return tuple(unique)

    def to_dict(self) -> dict:
        return {
            "method": self.method,
            "units": self.units,
            "base_value": round(self.base_value, 6),
            "summary": self.summary,
            "reasons": list(self.reasons),
            "model_reasons": list(self.model_reasons),
            "policy_reasons": list(self.policy_reasons),
            "factors": [factor.to_dict() for factor in self.factors],
        }


class Explainer:
    """Объясняет решения Risk Engine."""

    def __init__(self, engine: ContributionEngine, top_factors: int = MAX_FACTORS) -> None:
        self._engine = engine
        self.top_factors = max(MIN_FACTORS, min(MAX_FACTORS, top_factors))

    @classmethod
    def from_model(cls, model: Any, *, prefer_shap: bool = True, top_factors: int = MAX_FACTORS) -> Explainer:
        return cls(build_contribution_engine(model, prefer_shap=prefer_shap), top_factors)

    @property
    def method(self) -> str:
        return self._engine.name

    def explain(
        self,
        features: dict[str, float],
        assessment: RiskAssessment | None = None,
        language: Language = DEFAULT_LANGUAGE,
    ) -> Explanation:
        """Построить объяснение для транзакции.

        Args:
            features: вектор признаков, на котором считалось предсказание.
            assessment: результат Risk Engine — нужен, чтобы показать
                сработавшие политики и собрать итоговую формулировку.
        """
        missing = [name for name in FEATURE_NAMES if name not in features]
        if missing:
            raise ExplanationError(f"В векторе признаков нет: {missing}")

        try:
            result = self._engine.contributions(features)
        except Exception as exc:
            raise ExplanationError(f"Не удалось посчитать вклады признаков: {exc}") from exc

        factors = self._build_factors(result.values, features, language)
        policy_reasons = (
            tuple(rule.title.get(language) for rule in assessment.triggered_rules)
            if assessment
            else ()
        )

        summary = ""
        if assessment is not None:
            summary = narrator.summarise(
                risk_score=assessment.risk_score,
                decision=assessment.decision.value,
                factor_count=len(factors),
                rule_count=len(policy_reasons),
            )

        return Explanation(
            method=result.method,
            units=result.units,
            base_value=result.base_value,
            factors=factors,
            policy_reasons=policy_reasons,
            summary=summary,
        )

    # ------------------------------------------------------------ внутреннее

    def _build_factors(
        self,
        contributions: dict[str, float],
        features: dict[str, float],
        language: Language = DEFAULT_LANGUAGE,
    ) -> tuple[RiskFactor, ...]:
        """Отобрать и оформить топ факторов.

        Сначала берутся значимые вклады по убыванию модуля. Если значимых
        оказалось меньше трёх (транзакция ничем не примечательна), список
        дополняется следующими по величине — требование ТЗ §7 о минимум
        трёх факторах выполняется всегда.
        """
        ordered = sorted(contributions.items(), key=lambda item: abs(item[1]), reverse=True)

        meaningful = [item for item in ordered if not narrator.is_negligible(item[1])]
        selected = meaningful[: self.top_factors]

        if len(selected) < MIN_FACTORS:
            already = {name for name, _ in selected}
            for name, value in ordered:
                if len(selected) >= MIN_FACTORS:
                    break
                if name not in already:
                    selected.append((name, value))

        return tuple(
            self._make_factor(name, features.get(name, 0.0), contribution, language)
            for name, contribution in selected
        )

    @staticmethod
    def _make_factor(
        feature: str,
        value: float,
        contribution: float,
        language: Language = DEFAULT_LANGUAGE,
    ) -> RiskFactor:
        spec = get_spec(feature) if has_spec(feature) else None
        return RiskFactor(
            feature=feature,
            value=float(value),
            display_value=spec.format_value(value) if spec else f"{value:.2f}",
            contribution=float(contribution),
            direction=narrator.direction_of(contribution),
            reason=narrator.describe(feature, value, contribution, language),
            # Неизвестный признак описывается собственным именем —
            # техническим и одинаковым на всех языках.
            description=spec.description
            if spec
            else Text(ru=feature, kk=feature, en=feature),
        )
