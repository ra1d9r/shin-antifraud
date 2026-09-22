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
from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass, replace
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
class CountryStat:
    """Одна страна на карте аномалий (брифинг §6).

    Координаты берутся из того же справочника, что и признак
    «резкая смена геолокации» (`features/geo.py`). Второй набор
    координат — ради карты — разошёлся бы с тем, по которому
    считается скорость перемещения, и карта показывала бы не то
    место, где система увидела аномалию.
    """

    country: str
    latitude: float
    longitude: float
    rows: int
    fraud_rows: int
    #: Операции с решением, отличным от APPROVE.
    flagged: int
    #: Помечена ли страна как высокорисковая в справочнике.
    high_risk: bool

    @property
    def fraud_share(self) -> float:
        return self.fraud_rows / max(1, self.rows)

    @property
    def flagged_share(self) -> float:
        return self.flagged / max(1, self.rows)

    def to_dict(self) -> dict[str, Any]:
        return {
            "country": self.country,
            "latitude": round(self.latitude, 4),
            "longitude": round(self.longitude, 4),
            "rows": self.rows,
            "fraud_rows": self.fraud_rows,
            "flagged": self.flagged,
            "high_risk": self.high_risk,
            "fraud_share": round(self.fraud_share, 4),
            "flagged_share": round(self.flagged_share, 4),
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
    # Сумма сумм пропущенного фрода. Хранится отдельно от `fraud_loss`,
    # потому что та уже умножена на веса: имея только её, пересчитать
    # кривую на других весах нельзя. Веса — настраиваемая бизнес-метрика
    # (брифинг §5.C), и менять их, не пересчитывая кривую, значило бы
    # показывать на дашборде числа по старой метрике.
    #
    # `None` — точка из отчёта, выгруженного до появления этого поля.
    # Тогда пересчёт недоступен, и это честно сказано в ответе API.
    fraud_missed_amount: float | None = None

    @property
    def total_cost(self) -> float:
        return self.fraud_loss + self.friction_cost

    # Метрики качества выводятся из тех же счётчиков, а не считаются
    # заново: помеченное системой — это `fraud_stopped` плюс `friction`,
    # и второй проход по данным дал бы ровно те же числа, только с риском
    # однажды разойтись с первым.
    #
    # Брифинг §5.A требует «индикацию компромисса между точностью
    # (Precision/Recall) и потерями бизнеса», а стоимость уже лежит
    # в этой же точке — значит компромисс виден в одной строке.

    @property
    def precision(self) -> float | None:
        """Доля настоящего фрода среди помеченного.

        `None`, когда система не пометила никого: делить не на что,
        а ноль означал бы «всё помеченное оказалось честным» — другое
        утверждение.
        """
        flagged = self.fraud_stopped + self.friction
        return self.fraud_stopped / flagged if flagged else None

    @property
    def recall(self) -> float | None:
        """Доля пойманного фрода от всего фрода в выборке."""
        total_fraud = self.fraud_stopped + self.fraud_missed
        return self.fraud_stopped / total_fraud if total_fraud else None

    @property
    def f1(self) -> float | None:
        precision, recall = self.precision, self.recall
        if precision is None or recall is None or precision + recall == 0:
            return None
        return 2 * precision * recall / (precision + recall)

    def to_dict(self) -> dict[str, Any]:
        return {
            "threshold": self.threshold,
            "fraud_missed": self.fraud_missed,
            "fraud_stopped": self.fraud_stopped,
            "friction": self.friction,
            "fraud_loss": round(self.fraud_loss, 2),
            "friction_cost": round(self.friction_cost, 2),
            "fraud_missed_amount": (
                None if self.fraud_missed_amount is None else round(self.fraud_missed_amount, 2)
            ),
            "total_cost": round(self.total_cost, 2),
            "precision": None if self.precision is None else round(self.precision, 4),
            "recall": None if self.recall is None else round(self.recall, 4),
            "f1": None if self.f1 is None else round(self.f1, 4),
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
    #: Деньги фрода, которые система не пропустила, — «спасённый бюджет»
    #: из брифинга §5.A. Считается по тем же решениям, что и счётчики
    #: выше, а не по кривой: кривая моделирует один рычаг, а система
    #: работает тремя уровнями с политиками поверх.
    fraud_loss_prevented: float
    #: Деньги фрода, ушедшие с решением APPROVE.
    fraud_loss_incurred: float
    friction: int
    raised_by_rules: int

    #: Те же две величины, посчитанные по решениям одной модели, без политик.
    #: Нужны, чтобы обязательные метрики брифинга §5.A — «спасённый бюджет»
    #: и «процент ложных срабатываний» — было с чем сравнить: сами по себе
    #: они не показывают, чья это заслуга и чья вина.
    fraud_stopped_without_rules: int
    friction_without_rules: int

    #: География операций для карты аномалий (брифинг §6). Пустой
    #: кортеж означает, что в датасете не оказалось ни одной страны
    #: с известными координатами — карта тогда не рисуется.
    countries: tuple[CountryStat, ...]

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
    def fraud_loss_exposure(self) -> float:
        """Во что обошёлся бы весь фрод выборки без системы вовсе.

        Сумма двух предыдущих по построению: каждая мошенническая
        операция либо остановлена, либо пропущена, третьего нет.
        """
        return self.fraud_loss_prevented + self.fraud_loss_incurred

    @property
    def friction_share(self) -> float:
        """Доля добросовестных клиентов, которых система побеспокоила.

        Это и есть False Positive Rate из брифинга: знаменатель —
        все легальные транзакции, а не только заблокированные.
        """
        return self.friction / max(1, self.legit_rows)

    @property
    def fraud_stopped_share_without_rules(self) -> float:
        """Какую долю фрода остановила бы одна модель."""
        return self.fraud_stopped_without_rules / max(1, self.fraud_rows)

    @property
    def friction_share_without_rules(self) -> float:
        """Каким был бы False Positive Rate без политик."""
        return self.friction_without_rules / max(1, self.legit_rows)

    @property
    def rules_gained_fraud(self) -> int:
        """Фрод, пойманный политиками сверх модели.

        Считается по решениям целиком, а не суммированием по строкам
        таблицы политик: правила пересекаются, и сумма предельных вкладов
        посчитала бы одну операцию столько раз, сколько политик на ней
        сработало.
        """
        return self.fraud_stopped - self.fraud_stopped_without_rules

    @property
    def rules_added_friction(self) -> int:
        """Добросовестные клиенты, задетые политиками сверх модели."""
        return self.friction - self.friction_without_rules

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
            "fraud_loss_prevented": round(self.fraud_loss_prevented, 2),
            "fraud_loss_incurred": round(self.fraud_loss_incurred, 2),
            "fraud_loss_exposure": round(self.fraud_loss_exposure, 2),
            "friction": self.friction,
            "friction_share": round(self.friction_share, 4),
            "raised_by_rules": self.raised_by_rules,
            "fraud_stopped_without_rules": self.fraud_stopped_without_rules,
            "fraud_stopped_share_without_rules": round(self.fraud_stopped_share_without_rules, 4),
            "friction_without_rules": self.friction_without_rules,
            "friction_share_without_rules": round(self.friction_share_without_rules, 4),
            "rules_gained_fraud": self.rules_gained_fraud,
            "rules_added_friction": self.rules_added_friction,
            "countries": [item.to_dict() for item in self.countries],
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
                # Отчёт выгружается офлайн и на русском — языке проекта.
                # Переводы отдаёт API по `?language=`.
                title=rule.title.ru,
                min_score=rule.min_score,
                legit_hits=legit_hits[rule.key],
                fraud_hits=fraud_hits[rule.key],
                gained_fraud=gained_fraud,
                added_friction=added_friction,
            )
        )
    return tuple(stats)


def _fraud_money(
    decisions: list[Decision],
    amounts: list[float],
    is_fraud: list[bool],
    settings: Settings,
) -> tuple[float, float]:
    """Деньги фрода: остановленные и ушедшие.

    Цена одной мошеннической операции берётся той же формулой, что
    в `_total_cost`, — иначе «спасённый бюджет» на плитке и стоимость
    на кривой считались бы по разным правилам и не сходились бы.

    Проверка (CHALLENGE) считается остановкой. Это допущение модели
    стоимости, а не факт: клиент может подтвердить операцию и фрод
    пройдёт. Но то же допущение уже заложено в `_total_cost`, где
    потерю даёт только `fraud and APPROVE`, и разойтись с ним здесь
    значило бы получить две разные версии одной величины.
    """
    prevented = incurred = 0.0
    for decision, amount, fraud in zip(decisions, amounts, is_fraud, strict=True):
        if not fraud:
            continue
        loss = amount * settings.cost_fraud_loss_ratio + settings.cost_fraud_fixed
        if decision is Decision.APPROVE:
            incurred += loss
        else:
            prevented += loss
    return prevented, incurred


def _count_stopped(decisions: list[Decision], is_fraud: list[bool], *, fraud: bool) -> int:
    """Сколько операций система не пропустила: BLOCK или CHALLENGE.

    Один счётчик на два смысла: по мошенническим операциям это пойманный
    фрод, по легальным — трение. Считаются они одинаково, и держать две
    копии одного выражения значило бы однажды поправить только одну —
    тем более что теперь каждое из них вызывается дважды, для решений
    с политиками и без.
    """
    return sum(
        1
        for decision, is_fraud_row in zip(decisions, is_fraud, strict=True)
        # Сравнение, а не `is`: numpy-шный bool тождеством не совпал бы
        # с питоновским, и счётчик молча вернул бы ноль.
        if bool(is_fraud_row) == fraud and decision is not Decision.APPROVE
    )


def _country_stats(
    frame, decisions: list[Decision], is_fraud: list[bool]
) -> tuple[CountryStat, ...]:
    """Сводка по странам для карты аномалий.

    Страны без координат пропускаются молча: показать точку наугад
    хуже, чем не показать её вовсе — на карте это выглядело бы как
    операции из середины океана.
    """
    from app.features.geo import COUNTRY_COORDINATES, HIGH_RISK_COUNTRIES

    totals: dict[str, list[int]] = {}
    for country, decision, fraud in zip(frame["country"], decisions, is_fraud, strict=True):
        code = str(country).upper()
        if code not in COUNTRY_COORDINATES:
            continue
        counters = totals.setdefault(code, [0, 0, 0])
        counters[0] += 1
        counters[1] += int(bool(fraud))
        counters[2] += int(decision is not Decision.APPROVE)

    stats = []
    for code, (rows, fraud_rows, flagged) in totals.items():
        latitude, longitude = COUNTRY_COORDINATES[code]
        stats.append(
            CountryStat(
                country=code,
                latitude=latitude,
                longitude=longitude,
                rows=rows,
                fraud_rows=fraud_rows,
                flagged=flagged,
                high_risk=code in HIGH_RISK_COUNTRIES,
            )
        )
    # По убыванию объёма: так крупные страны рисуются первыми и мелкие
    # ложатся поверх, а не прячутся под ними.
    return tuple(sorted(stats, key=lambda item: -item.rows))


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
    # Оба списка отсортированы по счёту, и это используется: граница ищется
    # двоичным поиском, а стоимость пропуска берётся из префиксных сумм.
    # Раньше сортировка стояла, но каждый из 101 порога всё равно проходил
    # оба списка целиком — работа впустую и обманчивый вид оптимизации.
    fraud_sorted = sorted(
        (score, amount)
        for score, amount, fraud in zip(scores, amounts, is_fraud, strict=True)
        if fraud
    )
    fraud_scores = [score for score, _ in fraud_sorted]
    legit_scores = sorted(
        score for score, fraud in zip(scores, is_fraud, strict=True) if not fraud
    )

    # prefix[k] — сумма сумм k самых низкооценённых мошеннических операций.
    # Веса к ней не применяются: их применяет `cost_of`, и та же функция
    # пересчитывает кривую, когда веса меняют в рантайме.
    prefix = [0.0]
    for _, amount in fraud_sorted:
        prefix.append(prefix[-1] + amount)

    points = []
    for threshold in range(0, 101, CURVE_STEP):
        missed_count = bisect_right(fraud_scores, threshold)
        friction = len(legit_scores) - bisect_right(legit_scores, threshold)
        missed_amount = prefix[missed_count]

        points.append(
            _priced(
                CurvePoint(
                    threshold=threshold,
                    fraud_missed=missed_count,
                    fraud_stopped=len(fraud_sorted) - missed_count,
                    friction=friction,
                    fraud_loss=0.0,
                    friction_cost=0.0,
                    fraud_missed_amount=missed_amount,
                ),
                settings,
            )
        )
    return tuple(points)


def _priced(point: CurvePoint, settings: Settings) -> CurvePoint:
    """Проставить точке стоимость по текущим весам.

    Одна функция и для первой сборки отчёта, и для пересчёта в рантайме:
    две копии формулы разошлись бы, и тогда кривая на дашборде перестала
    бы отвечать той метрике, по которой система себя судит.
    """
    if point.fraud_missed_amount is None:
        return point
    return replace(
        point,
        fraud_loss=(
            point.fraud_missed_amount * settings.cost_fraud_loss_ratio
            + point.fraud_missed * settings.cost_fraud_fixed
        ),
        friction_cost=point.friction * settings.cost_false_challenge,
    )


def reprice_curve(curve: Sequence[dict[str, Any]], settings: Settings) -> list[dict[str, Any]] | None:
    """Пересчитать кривую на других весах — без данных, по счётчикам.

    Датасет в рантайме недоступен: образ удаляет его после обучения.
    Но кривой он и не нужен — в каждой точке уже лежат счётчики
    и сумма пропущенного фрода, а веса лишь превращают их в деньги.
    Поэтому веса можно менять на работающей системе (брифинг §5.C),
    и дашборд сразу показывает метрику, по которой его попросили судить.

    На вход и выход идут словари: именно в такой форме отчёт живёт
    в рантайме — он прочитан из JSON, а не собран из датаклассов.
    Формула при этом одна и та же, `_priced`: две копии разошлись бы,
    и кривая перестала бы отвечать той метрике, по которой система
    себя судит.

    `None`, когда отчёт выгружен до появления `fraud_missed_amount`:
    пересчитать нечем, и притвориться, что получилось, было бы хуже
    честного отказа.
    """
    points = []
    for row in curve:
        if row.get("fraud_missed_amount") is None:
            return None
        points.append(
            _priced(
                CurvePoint(
                    threshold=row["threshold"],
                    fraud_missed=row["fraud_missed"],
                    fraud_stopped=row["fraud_stopped"],
                    friction=row["friction"],
                    fraud_loss=0.0,
                    friction_cost=0.0,
                    fraud_missed_amount=row["fraud_missed_amount"],
                ),
                settings,
            )
        )
    return [point.to_dict() for point in points]


def cheapest_threshold(curve: Sequence[dict[str, Any]]) -> int | None:
    """Порог с наименьшей полной стоимостью.

    Та же выборка, что при сборке отчёта (`min` по `total_cost`), но по
    словарям: после пересчёта весов оптимум переезжает, и оставить
    прежний значило бы показывать на дашборде отметку не от этой кривой.
    """
    if not curve:
        return None
    return min(curve, key=lambda row: row["total_cost"])["threshold"]


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
    fraud_stopped = _count_stopped(decisions, is_fraud, fraud=True)
    friction = _count_stopped(decisions, is_fraud, fraud=False)

    bare = RiskEngine(thresholds=thresholds, rules=(), rules_enabled=False)
    bare_decisions = [
        bare.assess(probability, row).decision
        for probability, row in zip(probabilities, records, strict=True)
    ]

    prevented, incurred = _fraud_money(decisions, amounts, is_fraud, settings)

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
        fraud_loss_prevented=prevented,
        fraud_loss_incurred=incurred,
        friction=friction,
        raised_by_rules=sum(1 for item in assessments if item.raised_by_rules),
        fraud_stopped_without_rules=_count_stopped(bare_decisions, is_fraud, fraud=True),
        friction_without_rules=_count_stopped(bare_decisions, is_fraud, fraud=False),
        rules=(
            _rule_stats(settings, records, is_fraud, probabilities, thresholds)
            if rules_enabled
            else ()
        ),
        countries=_country_stats(frame, decisions, is_fraud),
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
