"""Оценка Risk Engine на всём потоке транзакций (ТЗ §8.1, брифинг §5.A и §11).

Модуль отвечает на вопросы, которые невозможно задать по одной транзакции:
сколько фрода система ловит, скольких добросовестных клиентов при этом
задевает и во что это обходится бизнесу.

## Почему расчёт живёт здесь, а не в скрипте

До этого модуля те же величины считались внутри `evaluate_risk_engine.py`
и существовали только на экране. Дашборду пришлось бы посчитать их
второй раз — а две копии одной формулы расходятся, и расхождение
замечают не сразу. Теперь считает модуль, а скрипт и HTTP-слой только
показывают.

## Почему результат кладётся в артефакт

Полный проход по 100 000 транзакций занимает около двадцати секунд:
признаки строятся построчно (ради отсутствия training/serving skew),
а предельный вклад каждой политики требует отдельного прогона движка.
Считать это на старте приложения нельзя — healthcheck не дождётся.
Поэтому отчёт выгружается в `backend/models/evaluation.json`, а
приложение его только читает. Тот же приём, что с `model_metrics.json`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config.settings import Settings
from app.core.exceptions import ShinError
from app.risk_engine.engine import RiskAssessment, RiskEngine, RiskThresholds
from app.risk_engine.rules import build_rules, evaluate_rules
from app.schemas.enums import Decision

# Шаг сетки порогов для кривой компромисса. Единица даёт 101 точку —
# достаточно подробно для графика и дёшево по времени.
CURVE_STEP = 1


class EvaluationNotFoundError(ShinError):
    """Артефакт с оценкой отсутствует — его нужно выгрузить скриптом."""

    status_code = 503
    error_code = "evaluation_not_found"


@dataclass(frozen=True, slots=True)
class DecisionRow:
    """Одна строка разбивки решений: сколько легальных и сколько фрода."""

    decision: str
    legit: int
    fraud: int

    def to_dict(self) -> dict[str, Any]:
        return {"decision": self.decision, "legit": self.legit, "fraud": self.fraud}


@dataclass(frozen=True, slots=True)
class RuleStat:
    """Статистика одной политики.

    `gained_fraud` и `added_friction` — предельный вклад: что политика
    меняет СВЕРХ того, что уже сделала модель. Срабатывание на транзакции,
    которую модель и так остановила, пользы не добавляет, а трение
    у добросовестного клиента добавляет всегда.
    """

    key: str
    title: str
    min_score: int
    legit_hits: int
    fraud_hits: int
    gained_fraud: int
    added_friction: int

    @property
    def precision(self) -> float:
        """Доля фрода среди всех срабатываний политики."""
        return self.fraud_hits / max(1, self.legit_hits + self.fraud_hits)

    @property
    def checks_per_fraud(self) -> float | None:
        """Сколько лишних проверок стоит один пойманный сверх модели фрод.

        None означает, что политика не поймала ничего, чего не поймала бы
        модель, — то есть приносит только трение.
        """
        if self.gained_fraud == 0:
            return None
        return self.added_friction / self.gained_fraud

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "title": self.title,
            "min_score": self.min_score,
            "legit_hits": self.legit_hits,
            "fraud_hits": self.fraud_hits,
            "precision": round(self.precision, 4),
            "gained_fraud": self.gained_fraud,
            "added_friction": self.added_friction,
            "checks_per_fraud": (
                None if self.checks_per_fraud is None else round(self.checks_per_fraud, 1)
            ),
        }


@dataclass(frozen=True, slots=True)
class CurvePoint:
    """Точка кривой компромисса при одном пороге чувствительности."""

    threshold: int
    fraud_missed: int
    fraud_stopped: int
    friction: int
    fraud_loss: float
    friction_cost: float

    @property
    def total_cost(self) -> float:
        return self.fraud_loss + self.friction_cost

    def to_dict(self) -> dict[str, Any]:
        return {
            "threshold": self.threshold,
            "fraud_missed": self.fraud_missed,
            "fraud_stopped": self.fraud_stopped,
            "friction": self.friction,
            "fraud_loss": round(self.fraud_loss, 2),
            "friction_cost": round(self.friction_cost, 2),
            "total_cost": round(self.total_cost, 2),
        }


@dataclass(frozen=True, slots=True)
class DatasetReport:
    """Полная картина работы системы на датасете."""

    generated_at: str
    # Метка модели, на которой посчитан отчёт. Без неё артефакт молча
    # устаревает при переобучении: числа на дашборде остаются от прежней
    # модели, и заметить это можно только случайно. Ровно так однажды
    # устарели метрики в README.
    model_trained_at: str | None
    model_algorithm: str | None
    rows: int
    fraud_rows: int
    legit_rows: int
    total_amount: float
    thresholds: dict[str, int]
    rules_enabled: bool

    decisions: tuple[DecisionRow, ...]
    fraud_blocked: int
    fraud_stopped: int
    fraud_missed: int
    friction: int
    raised_by_rules: int

    rules: tuple[RuleStat, ...]
    cost_with_rules: float
    cost_without_rules: float

    curve: tuple[CurvePoint, ...]
    optimal_threshold: int

    @property
    def fraud_rate(self) -> float:
        return self.fraud_rows / max(1, self.rows)

    @property
    def fraud_stopped_share(self) -> float:
        return self.fraud_stopped / max(1, self.fraud_rows)

    @property
    def friction_share(self) -> float:
        """Доля добросовестных клиентов, которых система побеспокоила.

        Это и есть False Positive Rate из брифинга: знаменатель —
        все легальные транзакции, а не только заблокированные.
        """
        return self.friction / max(1, self.legit_rows)

    @property
    def rules_cost_delta(self) -> float:
        """Во что обходятся политики сверх чистой модели. Меньше нуля — окупаются."""
        return self.cost_with_rules - self.cost_without_rules

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "model_trained_at": self.model_trained_at,
            "model_algorithm": self.model_algorithm,
            "rows": self.rows,
            "fraud_rows": self.fraud_rows,
            "legit_rows": self.legit_rows,
            "fraud_rate": round(self.fraud_rate, 6),
            "total_amount": round(self.total_amount, 2),
            "thresholds": self.thresholds,
            "rules_enabled": self.rules_enabled,
            "decisions": [row.to_dict() for row in self.decisions],
            "fraud_blocked": self.fraud_blocked,
            "fraud_stopped": self.fraud_stopped,
            "fraud_missed": self.fraud_missed,
            "fraud_stopped_share": round(self.fraud_stopped_share, 4),
            "friction": self.friction,
            "friction_share": round(self.friction_share, 4),
            "raised_by_rules": self.raised_by_rules,
            "rules": [rule.to_dict() for rule in self.rules],
            "cost_with_rules": round(self.cost_with_rules, 2),
            "cost_without_rules": round(self.cost_without_rules, 2),
            "rules_cost_delta": round(self.rules_cost_delta, 2),
            "curve": [point.to_dict() for point in self.curve],
            "optimal_threshold": self.optimal_threshold,
        }


# --------------------------------------------------------------- расчёт


def _decision_breakdown(
    assessments: list[RiskAssessment], is_fraud: list[bool]
) -> tuple[DecisionRow, ...]:
    counts: dict[str, list[int]] = {
        Decision.APPROVE.value: [0, 0],
        Decision.CHALLENGE.value: [0, 0],
        Decision.BLOCK.value: [0, 0],
    }
    for assessment, fraud in zip(assessments, is_fraud, strict=True):
        counts[assessment.decision.value][1 if fraud else 0] += 1

    return tuple(
        DecisionRow(decision=name, legit=pair[0], fraud=pair[1])
        for name, pair in counts.items()
    )


def _rule_stats(
    settings: Settings,
    records: list[dict],
    is_fraud: list[bool],
    probabilities,
    thresholds: RiskThresholds,
) -> tuple[RuleStat, ...]:
    """Срабатывания политик и их предельный вклад сверх чистой модели."""
    rules = build_rules(settings)

    legit_hits: dict[str, int] = {rule.key: 0 for rule in rules}
    fraud_hits: dict[str, int] = {rule.key: 0 for rule in rules}
    for row, fraud in zip(records, is_fraud, strict=True):
        for triggered in evaluate_rules(rules, row):
            (fraud_hits if fraud else legit_hits)[triggered.key] += 1

    # Базовая линия: движок без политик. С ней сравнивается каждая политика,
    # включённая поодиночке.
    bare = RiskEngine(thresholds=thresholds, rules=(), rules_enabled=False)
    bare_decisions = [
        bare.assess(probability, row).decision
        for probability, row in zip(probabilities, records, strict=True)
    ]

    stats = []
    for rule in rules:
        solo = RiskEngine(thresholds=thresholds, rules=(rule,), rules_enabled=True)
        gained_fraud = 0
        added_friction = 0
        for base, probability, row, fraud in zip(
            bare_decisions, probabilities, records, is_fraud, strict=True
        ):
            if base is not Decision.APPROVE:
                continue  # модель уже остановила — политике нечего добавить
            if solo.assess(probability, row).decision is not Decision.APPROVE:
                if fraud:
                    gained_fraud += 1
                else:
                    added_friction += 1

        stats.append(
            RuleStat(
                key=rule.key,
                title=rule.title,
                min_score=rule.min_score,
                legit_hits=legit_hits[rule.key],
                fraud_hits=fraud_hits[rule.key],
                gained_fraud=gained_fraud,
                added_friction=added_friction,
            )
        )
    return tuple(stats)


def _total_cost(
    decisions: list[Decision], amounts: list[float], is_fraud: list[bool], settings: Settings
) -> float:
    """Бизнес-стоимость набора решений по модели стоимости из конфигурации."""
    cost = 0.0
    for decision, amount, fraud in zip(decisions, amounts, is_fraud, strict=True):
        if fraud and decision is Decision.APPROVE:
            cost += amount * settings.cost_fraud_loss_ratio + settings.cost_fraud_fixed
        elif not fraud and decision is Decision.BLOCK:
            cost += settings.cost_false_block
        elif not fraud and decision is Decision.CHALLENGE:
            cost += settings.cost_false_challenge
    return cost


def _trade_off_curve(
    scores: list[int], amounts: list[float], is_fraud: list[bool], settings: Settings
) -> tuple[CurvePoint, ...]:
    """Кривая компромисса: что происходит при каждом пороге чувствительности.

    Моделируется один рычаг: всё, что выше порога, уходит на проверку.
    Строго выше: операция со счётом ровно на пороге одобряется — так же,
    как в самой системе, где `risk_score <= approve_max` даёт APPROVE.
    Это упрощение против трёх зон системы, и оно намеренно — иначе график
    зависел бы от двух порогов сразу и перестал бы читаться. Зато вопрос
    «куда двигать чувствительность» он отвечает прямо.
    """
    fraud_amounts = sorted(
        (score, amount) for score, amount, fraud in zip(scores, amounts, is_fraud, strict=True) if fraud
    )
    legit_scores = sorted(
        score for score, fraud in zip(scores, is_fraud, strict=True) if not fraud
    )

    points = []
    for threshold in range(0, 101, CURVE_STEP):
        missed = [amount for score, amount in fraud_amounts if score <= threshold]
        friction = sum(1 for score in legit_scores if score > threshold)

        fraud_loss = sum(
            amount * settings.cost_fraud_loss_ratio + settings.cost_fraud_fixed
            for amount in missed
        )
        points.append(
            CurvePoint(
                threshold=threshold,
                fraud_missed=len(missed),
                fraud_stopped=len(fraud_amounts) - len(missed),
                friction=friction,
                fraud_loss=fraud_loss,
                friction_cost=friction * settings.cost_false_challenge,
            )
        )
    return tuple(points)


def build_report(
    frame,
    features,
    labels,
    probabilities,
    *,
    settings: Settings,
    thresholds: RiskThresholds,
    model=None,
    rules_enabled: bool = True,
) -> DatasetReport:
    """Посчитать полный отчёт по датасету.

    Args:
        frame: исходный датасет — нужен ради колонки `amount`.
        features: матрица признаков, построенная тем же кодом, что в проде.
        labels: целевая переменная (1 — фрод).
        probabilities: вероятности фрода от модели.
        settings: конфигурация, включая параметры стоимости.
        thresholds: пороги решений.
        model: обученная модель — нужна только ради метки в отчёте, чтобы
            было видно, к какой модели относятся числа.
        rules_enabled: считать ли с политиками поверх модели.
    """
    records = features.to_dict(orient="records")
    is_fraud = [bool(value) for value in labels]
    amounts = [float(value) for value in frame["amount"]]

    engine = RiskEngine(
        thresholds=thresholds,
        rules=build_rules(settings),
        rules_enabled=rules_enabled,
    )
    assessments = [
        engine.assess(probability, row)
        for probability, row in zip(probabilities, records, strict=True)
    ]
    decisions = [item.decision for item in assessments]
    scores = [item.risk_score for item in assessments]

    fraud_rows = sum(is_fraud)
    fraud_blocked = sum(
        1 for decision, fraud in zip(decisions, is_fraud, strict=True)
        if fraud and decision is Decision.BLOCK
    )
    fraud_stopped = sum(
        1 for decision, fraud in zip(decisions, is_fraud, strict=True)
        if fraud and decision is not Decision.APPROVE
    )
    friction = sum(
        1 for decision, fraud in zip(decisions, is_fraud, strict=True)
        if not fraud and decision is not Decision.APPROVE
    )

    bare = RiskEngine(thresholds=thresholds, rules=(), rules_enabled=False)
    bare_decisions = [
        bare.assess(probability, row).decision
        for probability, row in zip(probabilities, records, strict=True)
    ]

    curve = _trade_off_curve(scores, amounts, is_fraud, settings)
    optimal = min(curve, key=lambda point: point.total_cost).threshold

    return DatasetReport(
        generated_at=datetime.now(UTC).replace(microsecond=0).isoformat(),
        model_trained_at=getattr(model, "trained_at", None),
        model_algorithm=getattr(model, "algorithm", None),
        rows=len(records),
        fraud_rows=fraud_rows,
        legit_rows=len(records) - fraud_rows,
        total_amount=sum(amounts),
        thresholds=thresholds.to_dict(),
        rules_enabled=rules_enabled,
        decisions=_decision_breakdown(assessments, is_fraud),
        fraud_blocked=fraud_blocked,
        fraud_stopped=fraud_stopped,
        fraud_missed=fraud_rows - fraud_stopped,
        friction=friction,
        raised_by_rules=sum(1 for item in assessments if item.raised_by_rules),
        rules=(
            _rule_stats(settings, records, is_fraud, probabilities, thresholds)
            if rules_enabled
            else ()
        ),
        cost_with_rules=_total_cost(decisions, amounts, is_fraud, settings),
        cost_without_rules=_total_cost(bare_decisions, amounts, is_fraud, settings),
        curve=curve,
        optimal_threshold=optimal,
    )


# --------------------------------------------------------------- артефакт


def load_report(path: Path) -> dict[str, Any]:
    """Прочитать выгруженный отчёт.

    Возвращается словарь, а не `DatasetReport`: HTTP-слою нужен именно он,
    а собирать датаклассы обратно из JSON только ради того, чтобы тут же
    их разобрать, — работа впустую.
    """
    if not path.exists():
        raise EvaluationNotFoundError(
            f"Аналитика не выгружена: {path}. "
            "Выполните: python backend/scripts/export_evaluation.py"
        )
    return json.loads(path.read_text(encoding="utf-8"))
