"""Теневой режим: вторая конфигурация на том же потоке, без риска для клиента.

## Зачем

Дашборд уже показал две неприятные вещи: текущий порог 30 далеко от самого
дешёвого (4), а четыре политики из шести не ловят ничего сверх модели
и приносят одно трение.

Но по этим числам никто не станет трогать работающую систему, и правильно
не станет. Кривая компромисса отвечает на вопрос «что было бы на обучающем
датасете». Вопрос, на который надо ответить перед переключением, другой:
**что будет на сегодняшнем потоке**.

Теневой режим отвечает именно на него. Вторая конфигурация видит те же
настоящие транзакции, выносит свои решения — и они никуда не уходят.
Клиент их не видит, ответ API не меняется, деньги не блокируются. Меняется
только счётчик расхождений, по которому потом можно оценить последствия
переключения заранее.

## Почему это почти бесплатно

Дорогое в цепочке — построение признаков и прогон модели. И то и другое
уже сделано к моменту, когда решение принимает Risk Engine. Теневая
конфигурация переиспользует готовую вероятность и готовые признаки,
и ей остаётся арифметика с проверкой политик.

Движок с самого начала принимает пороги объектом, а не читает их из
конфигурации внутри, — ровно ради такого сценария (см. его docstring).

## Что хранится

Матрица три на три (решение основной против решения теневой) и кольцевой
буфер последних расхождений. Матрица — девять счётчиков, буфер ограничен.
Ни то ни другое не растёт с трафиком.
"""

from __future__ import annotations

import threading
from collections import Counter, deque
from dataclasses import dataclass
from datetime import UTC, datetime

from app.config.settings import Settings
from app.core.logging import get_logger
from app.risk_engine.engine import FeatureMap, RiskAssessment, RiskEngine, RiskThresholds
from app.risk_engine.rules import build_rules
from app.schemas.enums import Decision

logger = get_logger("shin.monitoring.shadow")

#: Сколько последних расхождений держать для разбора. Аналитику нужны
#: примеры, а не выгрузка: по десятку видно, что именно поменялось.
RECENT_LIMIT = 50

#: Решения, которыми система объявляет операцию подозрительной.
#: То же множество, что в разметке аналитика: «пометила» против «пропустила».
FLAGGED = frozenset({Decision.CHALLENGE, Decision.BLOCK})


@dataclass(frozen=True, slots=True)
class ShadowConfig:
    """Вторая конфигурация Risk Engine."""

    thresholds: RiskThresholds
    rules_enabled: bool

    @classmethod
    def from_settings(cls, settings: Settings) -> ShadowConfig:
        """Собрать теневую конфигурацию, наследуя незаданное у основной.

        Наследование, а не полная копия настроек: теневая конфигурация
        обычно отличается одним-двумя значениями, и требовать перечислить
        остальные значило бы завести второе место, где они разъезжаются
        с основными.
        """
        return cls(
            thresholds=RiskThresholds(
                approve_max=(
                    settings.shadow_approve_max
                    if settings.shadow_approve_max is not None
                    else settings.risk_approve_max
                ),
                challenge_max=(
                    settings.shadow_challenge_max
                    if settings.shadow_challenge_max is not None
                    else settings.risk_challenge_max
                ),
                critical_min=(
                    settings.shadow_critical_min
                    if settings.shadow_critical_min is not None
                    else settings.risk_critical_min
                ),
            ),
            rules_enabled=settings.shadow_rules_enabled,
        )

    def describe_difference(self, primary: RiskEngine) -> str:
        """Чем теневая отличается от основной — словами, для панели."""
        parts: list[str] = []
        if self.thresholds.approve_max != primary.thresholds.approve_max:
            parts.append(
                f"порог APPROVE {primary.thresholds.approve_max} → {self.thresholds.approve_max}"
            )
        if self.thresholds.challenge_max != primary.thresholds.challenge_max:
            parts.append(
                f"порог CHALLENGE {primary.thresholds.challenge_max} → "
                f"{self.thresholds.challenge_max}"
            )
        if self.thresholds.critical_min != primary.thresholds.critical_min:
            parts.append(
                f"порог CRITICAL {primary.thresholds.critical_min} → "
                f"{self.thresholds.critical_min}"
            )
        if self.rules_enabled != primary.rules_enabled:
            parts.append("политики выключены" if not self.rules_enabled else "политики включены")

        if not parts:
            return "совпадает с основной"
        return ", ".join(parts)


@dataclass(frozen=True, slots=True)
class Disagreement:
    """Операция, по которой конфигурации разошлись."""

    transaction_id: str
    user_id: str
    amount: float
    primary_decision: Decision
    primary_score: int
    shadow_decision: Decision
    shadow_score: int
    at: datetime


@dataclass(frozen=True, slots=True)
class MatrixCell:
    """Сколько операций получили такую пару решений."""

    primary: Decision
    shadow: Decision
    count: int
    amount: float


@dataclass(frozen=True, slots=True)
class ShadowReport:
    """Что дало бы переключение конфигурации на этом потоке."""

    enabled: bool
    differs: bool
    difference: str
    primary_thresholds: dict
    primary_rules_enabled: bool
    shadow_thresholds: dict
    shadow_rules_enabled: bool
    observed: int
    agreed: int
    disagreed: int
    agreement_share: float | None
    #: Основная пометила, теневая пропустила бы: снятое трение и риск.
    freed_count: int
    freed_amount: float
    #: Основная пропустила, теневая пометила бы: пойманное и новое трение.
    tightened_count: int
    tightened_amount: float
    matrix: tuple[MatrixCell, ...]
    recent: tuple[Disagreement, ...]


class ShadowRunner:
    """Прогоняет вторую конфигурацию рядом с основной и считает расхождения."""

    def __init__(self, engine: RiskEngine, config: ShadowConfig, primary: RiskEngine) -> None:
        self._engine = engine
        self._config = config
        self._primary = primary
        self._counts: Counter[tuple[Decision, Decision]] = Counter()
        self._amounts: Counter[tuple[Decision, Decision]] = Counter()
        self._recent: deque[Disagreement] = deque(maxlen=RECENT_LIMIT)
        self._observed = 0
        self._lock = threading.Lock()

    @classmethod
    def from_settings(cls, settings: Settings, primary: RiskEngine) -> ShadowRunner:
        config = ShadowConfig.from_settings(settings)
        engine = RiskEngine(
            thresholds=config.thresholds,
            # Правила строятся из тех же настроек: теневая конфигурация
            # меняет пороги и сам факт применения политик, а не их состав.
            # Иначе сравнение перестало бы быть сравнением «того же самого
            # при других настройках».
            rules=build_rules(settings),
            rules_enabled=config.rules_enabled,
        )
        return cls(engine=engine, config=config, primary=primary)

    @property
    def differs(self) -> bool:
        return (
            self._config.thresholds != self._primary.thresholds
            or self._config.rules_enabled != self._primary.rules_enabled
        )

    def assess(self, probability: float, features: FeatureMap | None) -> RiskAssessment:
        """Решение теневой конфигурации. Ничего не меняет и никуда не уходит."""
        return self._engine.assess(probability, features)

    def observe(
        self,
        *,
        primary: RiskAssessment,
        shadow: RiskAssessment,
        transaction_id: str,
        user_id: str,
        amount: float,
    ) -> None:
        """Учесть пару решений по одной операции."""
        key = (primary.decision, shadow.decision)
        with self._lock:
            self._observed += 1
            self._counts[key] += 1
            self._amounts[key] += amount
            if primary.decision is not shadow.decision:
                self._recent.appendleft(
                    Disagreement(
                        transaction_id=transaction_id,
                        user_id=user_id,
                        amount=amount,
                        primary_decision=primary.decision,
                        primary_score=primary.risk_score,
                        shadow_decision=shadow.decision,
                        shadow_score=shadow.risk_score,
                        at=datetime.now(UTC).replace(tzinfo=None),
                    )
                )

    def reset(self) -> None:
        with self._lock:
            self._counts.clear()
            self._amounts.clear()
            self._recent.clear()
            self._observed = 0

    def report(self, *, enabled: bool = True) -> ShadowReport:
        with self._lock:
            observed = self._observed
            counts = dict(self._counts)
            amounts = dict(self._amounts)
            recent = tuple(self._recent)

        agreed = sum(count for (left, right), count in counts.items() if left is right)
        disagreed = observed - agreed

        freed_count = freed_amount = 0
        tightened_count = tightened_amount = 0
        for (left, right), count in counts.items():
            if left in FLAGGED and right not in FLAGGED:
                freed_count += count
                freed_amount += amounts[(left, right)]
            elif left not in FLAGGED and right in FLAGGED:
                tightened_count += count
                tightened_amount += amounts[(left, right)]

        matrix = tuple(
            MatrixCell(
                primary=left,
                shadow=right,
                count=count,
                amount=round(amounts[(left, right)], 2),
            )
            for (left, right), count in sorted(
                counts.items(), key=lambda item: (item[0][0].value, item[0][1].value)
            )
        )

        return ShadowReport(
            enabled=enabled,
            differs=self.differs,
            difference=self._config.describe_difference(self._primary),
            primary_thresholds=self._primary.thresholds.to_dict(),
            primary_rules_enabled=self._primary.rules_enabled,
            shadow_thresholds=self._config.thresholds.to_dict(),
            shadow_rules_enabled=self._config.rules_enabled,
            observed=observed,
            agreed=agreed,
            disagreed=disagreed,
            # None, а не ноль: «согласия нет» и «сравнивать ещё нечего» —
            # разные утверждения, как и с точностью в разметке.
            agreement_share=round(agreed / observed, 4) if observed else None,
            freed_count=freed_count,
            freed_amount=round(freed_amount, 2),
            tightened_count=tightened_count,
            tightened_amount=round(tightened_amount, 2),
            matrix=matrix,
            recent=recent,
        )
