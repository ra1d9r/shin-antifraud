"""Адаптивный порог по категории мерчанта (брифинг §6).

Брифинг §6 просит «автоматическую подстройку чувствительности модели
в зависимости от времени суток или категории мерчанта».

## Почему пороги подбираются, а не назначаются

Назначить сдвиги руками было бы быстрее и полностью бессмысленно: это
третий слой захардкоженных чисел поверх модели, и угадать их нельзя.
Замер это подтверждает — интуиция даёт неверный знак. Кажется, что для
криптобирж и обменников порог надо **опускать**, раз там выводят
украденное. На деле подобранный порог у них выше общего: модель уже
учитывает категорию признаком `is_high_risk_merchant`, и низкий порог
поверх этого просто заваливает проверками честные операции.

Поэтому порог каждой категории берётся как минимум той же функции
стоимости, по которой строится кривая компромисса (ТЗ §10). Никаких
своих констант: и функция, и веса те же, что у остального проекта.

## Почему только категория, хотя брифинг называет и время суток

Проверено обе. На пятикратной перекрёстной проверке сегментация по
категории даёт в среднем выигрыш, по времени суток — в среднем убыток.
Числа лежат в артефакте вместе с таблицей порогов, и панель их
показывает: отрицательный результат — тоже результат, и прятать его
значило бы заявить работу, которой не было.

Брифинг говорит «времени суток **или** категории мерчанта», так что
одной категории достаточно.

## Чего этот модуль не делает

Не меняет `challenge_max` и `critical_min`. Подстраивается
чувствительность — граница между «пропустить» и «проверить», — а она
задаётся `approve_max`. Двигать заодно и остальные границы значило бы
менять смысл уровней риска, о котором никто не просил.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.exceptions import ShinError
from app.risk_engine.engine import MAX_SCORE, MIN_SCORE

#: Меньше этого числа мошеннических операций в сегменте — свой порог
#: не подбирается, берётся общий. На десятке случаев минимум функции
#: стоимости определяется одной крупной операцией, а не закономерностью.
MIN_FRAUD_PER_SEGMENT = 30

FORMAT_VERSION = "1"


class AdaptiveThresholdsNotFoundError(ShinError):
    """Артефакт с подобранными порогами отсутствует."""

    status_code = 503
    error_code = "adaptive_thresholds_not_found"


@dataclass(frozen=True, slots=True)
class SegmentThreshold:
    """Порог одного сегмента и данные, на которых он подобран."""

    segment: str
    approve_max: int
    rows: int
    fraud_rows: int
    #: False — данных не хватило, взят общий порог.
    fitted: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "segment": self.segment,
            "approve_max": self.approve_max,
            "rows": self.rows,
            "fraud_rows": self.fraud_rows,
            "fitted": self.fitted,
        }


@dataclass(frozen=True, slots=True)
class AdaptiveThresholds:
    """Подобранные пороги по сегментам плюс общий запасной."""

    fallback_approve_max: int
    segments: tuple[SegmentThreshold, ...]
    generated_at: str
    rows: int
    min_fraud_per_segment: int
    #: Что даёт режим на данных, которых не видел при подборе. None —
    #: пороги подобраны, но не проверены: показывать таблицу без этого
    #: значило бы выдать набор чисел за улучшение.
    validation: Validation | None = None

    def approve_max_for(self, segment: str | None) -> int:
        """Порог сегмента. Незнакомый сегмент получает общий.

        Незнакомый — это не ошибка: мерчант, которого нет в справочнике,
        даёт категорию `unknown`, и таких в обучающей выборке не было.
        """
        if segment is not None:
            for item in self.segments:
                if item.segment == segment:
                    return item.approve_max
        return self.fallback_approve_max

    def segment_names(self) -> tuple[str, ...]:
        return tuple(item.segment for item in self.segments)

    def to_dict(self) -> dict[str, Any]:
        return {
            "format_version": FORMAT_VERSION,
            "generated_at": self.generated_at,
            "rows": self.rows,
            "min_fraud_per_segment": self.min_fraud_per_segment,
            "fallback_approve_max": self.fallback_approve_max,
            "segments": [item.to_dict() for item in self.segments],
            "validation": None if self.validation is None else self.validation.to_dict(),
        }


# --------------------------------------------------------------- подбор


def _segment_cost(
    scores: list[int],
    labels: list[bool],
    fraud_costs: list[float],
    threshold: int,
    settings,
) -> float:
    """Стоимость сегмента при одном пороге.

    Та же модель, что у кривой компромисса в `analytics/report.py`:
    операция со счётом строго выше порога уходит на проверку, и это
    ровно то же правило, по которому `risk_score <= approve_max` даёт
    APPROVE в самом движке.
    """
    cost = 0.0
    for score, is_fraud, fraud_cost in zip(scores, labels, fraud_costs, strict=True):
        flagged = score > threshold
        if is_fraud and not flagged:
            cost += fraud_cost
        elif not is_fraud and flagged:
            cost += settings.cost_false_challenge
    return cost


def best_threshold(
    scores: list[int],
    labels: list[bool],
    fraud_costs: list[float],
    settings,
) -> int:
    """Порог с наименьшей стоимостью на этой выборке.

    При равенстве выигрывает меньший порог: он строже, а между двумя
    одинаково дешёвыми настройками антифрод выбирает осторожную.
    """
    return min(
        range(MIN_SCORE, MAX_SCORE + 1),
        key=lambda threshold: (
            _segment_cost(scores, labels, fraud_costs, threshold, settings),
            threshold,
        ),
    )


def fit(
    scores: list[int],
    labels: list[bool],
    amounts: list[float],
    segments: list[str],
    *,
    settings,
    min_fraud: int = MIN_FRAUD_PER_SEGMENT,
    validation: Validation | None = None,
) -> AdaptiveThresholds:
    """Подобрать порог каждому сегменту по функции стоимости.

    Args:
        scores: итоговый Risk Score каждой операции — тот же, по которому
            движок принимает решение, а не чистый выход модели.
        labels: известная разметка.
        amounts: суммы, нужны для цены пропущенного фрода.
        segments: к какому сегменту отнесена операция.
    """
    fraud_costs = [
        amount * settings.cost_fraud_loss_ratio + settings.cost_fraud_fixed for amount in amounts
    ]
    fallback = best_threshold(scores, labels, fraud_costs, settings)

    by_segment: dict[str, list[int]] = {}
    for index, segment in enumerate(segments):
        by_segment.setdefault(segment, []).append(index)

    fitted: list[SegmentThreshold] = []
    for segment in sorted(by_segment):
        rows = by_segment[segment]
        segment_labels = [labels[i] for i in rows]
        fraud_rows = sum(segment_labels)
        enough = fraud_rows >= min_fraud
        approve_max = (
            best_threshold(
                [scores[i] for i in rows],
                segment_labels,
                [fraud_costs[i] for i in rows],
                settings,
            )
            if enough
            else fallback
        )
        fitted.append(
            SegmentThreshold(
                segment=segment,
                approve_max=approve_max,
                rows=len(rows),
                fraud_rows=fraud_rows,
                fitted=enough,
            )
        )

    return AdaptiveThresholds(
        fallback_approve_max=fallback,
        segments=tuple(fitted),
        generated_at=datetime.now(UTC).replace(microsecond=0).isoformat(),
        rows=len(scores),
        min_fraud_per_segment=min_fraud,
        validation=validation,
    )


# ---------------------------------------------------------- проверка

#: На скольких частях проверяется выигрыш. Пять — обычный компромисс:
#: проверочная часть ещё достаточно велика, чтобы оценка не прыгала,
#: а подбор видит четыре пятых данных.
VALIDATION_FOLDS = 5


@dataclass(frozen=True, slots=True)
class Validation:
    """Что даёт адаптивный порог на данных, которых не видел при подборе.

    Без этого блока таблица порогов — просто набор чисел, про который
    нельзя сказать, помогает он или вредит. Проверка перекрёстная:
    порог сегмента подбирается без тех строк, на которых потом
    считается результат. Подбор и проверка на одних данных показали бы
    выигрыш, которого нет.

    Сравнений два, потому что вопросов два. `gain_*` отвечает, добавляет
    ли разбиение на сегменты что-нибудь сверх одного подобранного порога.
    `configured_*` отвечает оператору, что изменится, если включить режим
    на его нынешней настройке, — а она не обязана быть оптимальной.
    """

    folds: int
    #: Выигрыш против одного подобранного порога, по частям.
    gain_per_fold: tuple[float, ...]
    #: Стоимость при действующей настройке и при адаптивной.
    configured_approve_max: int
    configured_cost: float
    adaptive_cost: float
    configured_friction: int
    adaptive_friction: int
    configured_fraud_stopped: int
    adaptive_fraud_stopped: int

    @property
    def mean_gain(self) -> float:
        return sum(self.gain_per_fold) / len(self.gain_per_fold)

    @property
    def worst_gain(self) -> float:
        return min(self.gain_per_fold)

    @property
    def positive_folds(self) -> int:
        return sum(1 for value in self.gain_per_fold if value > 0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "folds": self.folds,
            "gain_per_fold": [round(value, 2) for value in self.gain_per_fold],
            "mean_gain": round(self.mean_gain, 2),
            "worst_gain": round(self.worst_gain, 2),
            "positive_folds": self.positive_folds,
            "configured_approve_max": self.configured_approve_max,
            "configured_cost": round(self.configured_cost, 2),
            "adaptive_cost": round(self.adaptive_cost, 2),
            "configured_friction": self.configured_friction,
            "adaptive_friction": self.adaptive_friction,
            "configured_fraud_stopped": self.configured_fraud_stopped,
            "adaptive_fraud_stopped": self.adaptive_fraud_stopped,
        }


def validate(
    scores: list[int],
    labels: list[bool],
    amounts: list[float],
    segments: list[str],
    *,
    settings,
    configured_approve_max: int,
    folds: int = VALIDATION_FOLDS,
    min_fraud: int = MIN_FRAUD_PER_SEGMENT,
) -> Validation:
    """Перекрёстная проверка адаптивного порога."""
    fraud_costs = [
        amount * settings.cost_fraud_loss_ratio + settings.cost_fraud_fixed for amount in amounts
    ]
    total = len(scores)
    by_segment: dict[str, list[int]] = {}
    for index, segment in enumerate(segments):
        by_segment.setdefault(segment, []).append(index)

    def subset(rows: list[int]) -> tuple[list[int], list[bool], list[float]]:
        return (
            [scores[i] for i in rows],
            [labels[i] for i in rows],
            [fraud_costs[i] for i in rows],
        )

    def cost_of(rows: list[int], threshold: int) -> float:
        return _segment_cost(*subset(rows), threshold, settings)

    gains: list[float] = []
    # Порог, назначенный каждой строке, когда её саму при подборе не видели.
    assigned = [0] * total

    for fold in range(folds):
        test_rows = [i for i in range(total) if i % folds == fold]
        fit_rows = [i for i in range(total) if i % folds != fold]
        fallback = best_threshold(*subset(fit_rows), settings)

        segmented_cost = 0.0
        for rows in by_segment.values():
            fit_segment = [i for i in rows if i % folds != fold]
            test_segment = [i for i in rows if i % folds == fold]
            if not test_segment:
                continue
            enough = sum(labels[i] for i in fit_segment) >= min_fraud
            threshold = best_threshold(*subset(fit_segment), settings) if enough else fallback
            segmented_cost += cost_of(test_segment, threshold)
            for i in test_segment:
                assigned[i] = threshold

        gains.append(cost_of(test_rows, fallback) - segmented_cost)

    every_row = list(range(total))
    adaptive_cost = sum(
        _segment_cost([scores[i]], [labels[i]], [fraud_costs[i]], assigned[i], settings)
        for i in every_row
    )

    def counts(threshold_of) -> tuple[int, int]:
        """Пойманный фрод и трение при заданном пороге у каждой строки."""
        stopped = friction = 0
        for i in every_row:
            flagged = scores[i] > threshold_of(i)
            if labels[i] and flagged:
                stopped += 1
            elif not labels[i] and flagged:
                friction += 1
        return stopped, friction

    configured_stopped, configured_friction = counts(lambda _: configured_approve_max)
    adaptive_stopped, adaptive_friction = counts(lambda i: assigned[i])

    return Validation(
        folds=folds,
        gain_per_fold=tuple(gains),
        configured_approve_max=configured_approve_max,
        configured_cost=cost_of(every_row, configured_approve_max),
        adaptive_cost=adaptive_cost,
        configured_friction=configured_friction,
        adaptive_friction=adaptive_friction,
        configured_fraud_stopped=configured_stopped,
        adaptive_fraud_stopped=adaptive_stopped,
    )


# ------------------------------------------------------------- артефакт


def save(thresholds: AdaptiveThresholds, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(thresholds.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load(path: Path) -> AdaptiveThresholds:
    """Прочитать подобранные пороги.

    Отсутствие артефакта — не поломка: система работает на общем пороге,
    как работала до появления этого модуля.
    """
    if not path.exists():
        raise AdaptiveThresholdsNotFoundError(
            f"Адаптивные пороги не подобраны: {path}. "
            "Выполните: python backend/scripts/export_evaluation.py"
        )

    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("format_version") != FORMAT_VERSION:
        raise AdaptiveThresholdsNotFoundError(
            f"Артефакт адаптивных порогов версии {payload.get('format_version')!r}, "
            f"ожидается {FORMAT_VERSION!r}. Выгрузите заново."
        )

    return AdaptiveThresholds(
        fallback_approve_max=int(payload["fallback_approve_max"]),
        segments=tuple(
            SegmentThreshold(
                segment=str(item["segment"]),
                approve_max=int(item["approve_max"]),
                rows=int(item["rows"]),
                fraud_rows=int(item["fraud_rows"]),
                fitted=bool(item["fitted"]),
            )
            for item in payload["segments"]
        ),
        generated_at=str(payload["generated_at"]),
        rows=int(payload["rows"]),
        min_fraud_per_segment=int(payload["min_fraud_per_segment"]),
        validation=_validation_from(payload.get("validation")),
    )


def _validation_from(payload: dict[str, Any] | None) -> Validation | None:
    if not payload:
        return None
    return Validation(
        folds=int(payload["folds"]),
        gain_per_fold=tuple(float(value) for value in payload["gain_per_fold"]),
        configured_approve_max=int(payload["configured_approve_max"]),
        configured_cost=float(payload["configured_cost"]),
        adaptive_cost=float(payload["adaptive_cost"]),
        configured_friction=int(payload["configured_friction"]),
        adaptive_friction=int(payload["adaptive_friction"]),
        configured_fraud_stopped=int(payload["configured_fraud_stopped"]),
        adaptive_fraud_stopped=int(payload["adaptive_fraud_stopped"]),
    )
