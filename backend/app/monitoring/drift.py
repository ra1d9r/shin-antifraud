"""Сдвиг распределения признаков: прод против обучающей выборки.

## Зачем

Модель обучена на сгенерированном датасете и с тех пор не менялась. Живой
поток меняться будет — другие суммы, другие страны, другие часы. Когда
входные данные перестают походить на обучающие, оценки модели становятся
недостоверными, и **система об этом молчит**: она по-прежнему отвечает
числом от 0 до 100, просто число уже ни о чём не говорит.

Ошибка здесь не падает с исключением и не видна в логах. Заметить её можно
только одним способом — сравнивать распределения.

## Чем меряем

Population Stability Index — стандартная мера в скоринге:

```
PSI = Σ (доля_прод − доля_эталон) · ln(доля_прод / доля_эталон)
```

Принятые границы: до 0.1 — стабильно, 0.1–0.25 — умеренный сдвиг,
дальше — существенный. Эти границы взяты как отраслевая договорённость,
а не выведены из наших данных, и относиться к ним нужно соответственно:
это повод посмотреть, а не приговор.

Выбран PSI, а не расстояние Колмогорова—Смирнова, по двум причинам.
Он считается по корзинам, то есть **не требует хранить наблюдения** —
достаточно счётчиков. И он привычен тем, кто занимается риск-моделями,
то есть читателю этого дашборда.

## Что хранится в памяти

Только счётчики по корзинам: 27 признаков на десяток корзин — три сотни
целых чисел независимо от того, миллион транзакций прошёл или три.
Сами значения не сохраняются, поэтому наблюдение ничего не знает
о клиентах и не растёт со временем.

Счётчики живут до перезапуска и на диск не пишутся: в отличие от разметки
аналитика, их восстанавливает обычный трафик.
"""

from __future__ import annotations

import json
import math
import threading
from bisect import bisect_right
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from itertools import pairwise
from pathlib import Path

from app.core.exceptions import ShinError
from app.core.logging import get_logger
from app.features.definitions import FEATURE_SPECS

logger = get_logger("shin.monitoring.drift")

#: Границы интерпретации PSI — отраслевая договорённость скоринга.
PSI_STABLE_MAX = 0.10
PSI_MODERATE_MAX = 0.25

#: Ниже этого числа наблюдений PSI считается, но не показывается:
#: на полусотне транзакций он меряет случайность, а не сдвиг.
MIN_OBSERVATIONS = 200

#: Подстановка вместо нулевой доли. Без неё логарифм уходит в бесконечность
#: на первой же корзине, куда в проде никто не попал. Значение заметно
#: меньше доли одной транзакции из тысячи, поэтому на живых данных
#: оно не искажает результат, но делает его конечным.
PSI_EPSILON = 1e-4

#: Децили: десять корзин — обычная практика для PSI.
QUANTILES: tuple[float, ...] = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)

#: Граница для бинарного признака. `bisect_right` разложит 0 и 1 по разные
#: стороны, поэтому флаг не требует отдельной ветки в коде.
FLAG_EDGE = 0.5

BASELINE_FORMAT_VERSION = "1"

_DESCRIPTIONS: dict[str, str] = {spec.name: spec.description for spec in FEATURE_SPECS}


class BaselineNotFoundError(ShinError):
    """Эталонное распределение не выгружено."""

    status_code = 503
    error_code = "baseline_not_found"


class BaselineMismatchError(ShinError):
    """Эталон снят с другого набора признаков."""

    status_code = 503
    error_code = "baseline_mismatch"


class DriftStatus(StrEnum):
    """Во что сложился PSI признака или всей картины."""

    STABLE = "STABLE"
    MODERATE = "MODERATE"
    SIGNIFICANT = "SIGNIFICANT"
    #: Признак в обучающей выборке постоянен — сравнивать нечего.
    NOT_MEASURABLE = "NOT_MEASURABLE"
    #: Наблюдений слишком мало, чтобы называть число.
    COLLECTING = "COLLECTING"


def classify(psi: float) -> DriftStatus:
    if psi < PSI_STABLE_MAX:
        return DriftStatus.STABLE
    if psi < PSI_MODERATE_MAX:
        return DriftStatus.MODERATE
    return DriftStatus.SIGNIFICANT


def population_stability_index(
    expected: list[float] | tuple[float, ...],
    observed: list[float] | tuple[float, ...],
) -> float:
    """PSI по двум наборам долей одинаковой длины.

    Доли, а не счётчики: сравниваются формы распределений, а размеры
    выборок заведомо разные.
    """
    if len(expected) != len(observed):
        raise ValueError("наборы долей разной длины")

    total = 0.0
    for want, got in zip(expected, observed, strict=True):
        want = max(want, PSI_EPSILON)
        got = max(got, PSI_EPSILON)
        total += (got - want) * math.log(got / want)
    return total


@dataclass(frozen=True, slots=True)
class FeatureBaseline:
    """Эталонное распределение одного признака.

    `edges` — внутренние границы корзин. Номер корзины для значения —
    `bisect_right(edges, value)`, поэтому корзин ровно на одну больше,
    чем границ. Пустые границы означают, что признак в обучающей выборке
    постоянен: корзина одна, и сдвиг по нему не определён.
    """

    name: str
    edges: tuple[float, ...]
    expected: tuple[float, ...]
    labels: tuple[str, ...]

    @property
    def measurable(self) -> bool:
        return len(self.expected) > 1

    def bin_of(self, value: float) -> int:
        return bisect_right(self.edges, value)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "edges": list(self.edges),
            "expected": list(self.expected),
            "labels": list(self.labels),
        }

    @classmethod
    def from_dict(cls, payload: dict) -> FeatureBaseline:
        return cls(
            name=str(payload["name"]),
            edges=tuple(float(edge) for edge in payload["edges"]),
            expected=tuple(float(share) for share in payload["expected"]),
            labels=tuple(str(label) for label in payload["labels"]),
        )


@dataclass(frozen=True, slots=True)
class DriftBaseline:
    """С чем сравнивается прод: снимок обучающего распределения."""

    generated_at: str
    model_trained_at: str | None
    rows: int
    features: tuple[FeatureBaseline, ...]
    format_version: str = BASELINE_FORMAT_VERSION

    def to_dict(self) -> dict:
        return {
            "format_version": self.format_version,
            "generated_at": self.generated_at,
            "model_trained_at": self.model_trained_at,
            "rows": self.rows,
            "features": [feature.to_dict() for feature in self.features],
        }

    @classmethod
    def from_dict(cls, payload: dict) -> DriftBaseline:
        return cls(
            format_version=str(payload.get("format_version", BASELINE_FORMAT_VERSION)),
            generated_at=str(payload["generated_at"]),
            model_trained_at=payload.get("model_trained_at"),
            rows=int(payload["rows"]),
            features=tuple(
                FeatureBaseline.from_dict(item) for item in payload["features"]
            ),
        )


# ----------------------------------------------------------- построение


def _numeric_edges(values) -> tuple[float, ...]:
    """Границы корзин по децилям обучающей выборки.

    Граница ставится **между** соседними наблюдаемыми значениями, а не на
    само значение дециля. Иначе у признаков с повторами получаются пустые
    корзины: `np.quantile` возвращает существующее значение, а
    `bisect_right` относит его к верхней корзине, и нижняя остаётся ни с чем.

    Так это выглядело на `txn_count_last_hour`, где 95 % строк — единица:
    все девять децилей равны 1.0, граница встаёт на 1.0, и вся выборка
    уезжает в верхнюю корзину. Ожидаемая доля нижней — ноль, то есть
    сравнение с подставленным эпсилоном вместо честного, а двойка,
    которая отличала 5 % трафика, теряется.

    Со сдвигом на середину интервала каждая корзина содержит как минимум
    то значение, из которого её граница выведена, — пустых не бывает
    по построению. Признак с единственным значением границ не получает
    вовсе: сравнивать там нечего.
    """
    import numpy as np

    distinct = np.unique(values)
    if distinct.size <= 1:
        return ()

    cuts = np.unique(np.quantile(values, QUANTILES))

    edges: set[float] = set()
    for cut in cuts:
        # Первое наблюдаемое значение строго правее дециля.
        position = int(np.searchsorted(distinct, cut, side="right"))
        if position >= distinct.size:
            continue  # дециль совпал с максимумом — правее ставить нечего
        edge = (float(cut) + float(distinct[position])) / 2.0
        if math.isfinite(edge):
            edges.add(round(edge, 6))

    return tuple(sorted(edges))


def _shares(counts: list[int], total: int) -> tuple[float, ...]:
    if total <= 0:
        return tuple(0.0 for _ in counts)
    return tuple(round(count / total, 6) for count in counts)


def _labels_for(edges: tuple[float, ...], *, is_flag: bool) -> tuple[str, ...]:
    if is_flag:
        return ("нет", "да")
    if not edges:
        return ("всё",)

    def fmt(value: float) -> str:
        return f"{value:g}"

    labels = [f"< {fmt(edges[0])}"]
    labels.extend(f"{fmt(left)}–{fmt(right)}" for left, right in pairwise(edges))
    labels.append(f"≥ {fmt(edges[-1])}")
    return tuple(labels)


def build_baseline(features, *, model_trained_at: str | None) -> DriftBaseline:
    """Снять эталон с матрицы признаков обучающего датасета.

    Флаги раскладываются на «нет» и «да», числовые — по децилям.
    Ожидаемые доли берутся фактические, а не равные 0.1: после чистки
    дубликатов границ корзины перестают быть равнонаполненными.

    Args:
        features: DataFrame с колонками `FEATURE_NAMES`.
    """
    import numpy as np

    rows = len(features)
    built: list[FeatureBaseline] = []

    for spec in FEATURE_SPECS:
        if spec.name not in features.columns:
            logger.warning("Признака %s нет в датасете — пропускаю", spec.name)
            continue

        column = np.asarray(features[spec.name], dtype=float)
        finite = column[np.isfinite(column)]
        edges = (FLAG_EDGE,) if spec.is_flag else _numeric_edges(finite)

        counts = [0] * (len(edges) + 1)
        for value in finite:
            counts[bisect_right(edges, float(value))] += 1

        built.append(
            FeatureBaseline(
                name=spec.name,
                edges=edges,
                expected=_shares(counts, int(finite.size)),
                labels=_labels_for(edges, is_flag=spec.is_flag),
            )
        )

    return DriftBaseline(
        generated_at=datetime.now(UTC).replace(microsecond=0).isoformat(),
        model_trained_at=model_trained_at,
        rows=rows,
        features=tuple(built),
    )


def load_baseline(path: Path) -> DriftBaseline:
    """Прочитать эталон с диска и убедиться, что он про эти признаки.

    Метка модели здесь намеренно **не** проверяется. Эталон описывает
    датасет, а не модель: переобучение на тех же данных распределение
    признаков не двигает, и предупреждение «устарел» было бы ложным.
    Устаревает эталон от другого — от смены датасета или кода признаков.

    Смену датасета поймать нечем, а вот смену набора признаков — можно,
    и это как раз случай, когда эталон становится непригоден, а не
    подозрителен. Поэтому имена сверяются строго, и несовпадение
    отключает наблюдение, а не помечает его звёздочкой.
    """
    if not path.exists():
        raise BaselineNotFoundError(
            f"Эталон распределения не найден: {path}. "
            "Выгрузите: python backend/scripts/export_evaluation.py"
        )

    baseline = DriftBaseline.from_dict(json.loads(path.read_text(encoding="utf-8")))

    expected = tuple(spec.name for spec in FEATURE_SPECS)
    actual = tuple(feature.name for feature in baseline.features)
    if actual != expected:
        raise BaselineMismatchError(
            f"Эталон снят с другого набора признаков: в нём {len(actual)}, "
            f"в системе {len(expected)}. Выгрузите заново: "
            "python backend/scripts/export_evaluation.py"
        )

    return baseline


# --------------------------------------------------------------- отчёт


@dataclass(frozen=True, slots=True)
class FeatureDrift:
    """Насколько один признак в проде разошёлся с обучающим."""

    name: str
    description: str
    status: DriftStatus
    psi: float | None
    labels: tuple[str, ...]
    expected: tuple[float, ...]
    observed: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class DriftReport:
    """Сводка по сдвигу распределения."""

    status: DriftStatus
    observed_rows: int
    baseline_rows: int
    baseline_generated_at: str
    model_trained_at: str | None
    min_observations: int
    enough_data: bool
    drifted: int
    invalid_values: int
    features: tuple[FeatureDrift, ...]


class DriftMonitor:
    """Счётчики корзин по живому потоку и сравнение их с эталоном."""

    def __init__(self, baseline: DriftBaseline) -> None:
        self._baseline = baseline
        self._counts: dict[str, list[int]] = {
            feature.name: [0] * len(feature.expected) for feature in baseline.features
        }
        self._observed = 0
        self._invalid = 0
        self._lock = threading.Lock()

    @property
    def baseline(self) -> DriftBaseline:
        return self._baseline

    @property
    def observed_rows(self) -> int:
        with self._lock:
            return self._observed

    def observe(self, features: Mapping[str, float]) -> None:
        """Учесть одну обработанную транзакцию.

        Значения не сохраняются — только увеличивается счётчик корзины.
        Нечисловое или бесконечное значение в корзину не попадает и
        считается отдельно: признаки такими быть не должны, и молчаливое
        округление скрыло бы поломку feature engineering.
        """
        with self._lock:
            self._observed += 1
            for feature in self._baseline.features:
                value = features.get(feature.name)
                if value is None:
                    continue
                number = float(value)
                if not math.isfinite(number):
                    self._invalid += 1
                    continue
                self._counts[feature.name][feature.bin_of(number)] += 1

    def reset(self) -> None:
        with self._lock:
            for counts in self._counts.values():
                for index in range(len(counts)):
                    counts[index] = 0
            self._observed = 0
            self._invalid = 0

    def report(self) -> DriftReport:
        """Сравнить накопленное с эталоном.

        Признаки идут по убыванию PSI: разошедшееся должно быть сверху,
        иначе на списке из двадцати семи строк его никто не заметит.
        """
        with self._lock:
            observed_rows = self._observed
            invalid = self._invalid
            snapshot = {name: list(counts) for name, counts in self._counts.items()}

        enough = observed_rows >= MIN_OBSERVATIONS
        rows: list[FeatureDrift] = []

        for feature in self._baseline.features:
            counts = snapshot[feature.name]
            total = sum(counts)
            observed = _shares(counts, total)

            if not feature.measurable:
                status, psi = DriftStatus.NOT_MEASURABLE, None
            elif not enough:
                status, psi = DriftStatus.COLLECTING, None
            else:
                psi = round(population_stability_index(feature.expected, observed), 4)
                status = classify(psi)

            rows.append(
                FeatureDrift(
                    name=feature.name,
                    description=_DESCRIPTIONS.get(feature.name, feature.name),
                    status=status,
                    psi=psi,
                    labels=feature.labels,
                    expected=feature.expected,
                    observed=observed,
                )
            )

        rows.sort(key=lambda row: (row.psi is None, -(row.psi or 0.0), row.name))
        drifted = sum(1 for row in rows if row.psi is not None and row.psi >= PSI_STABLE_MAX)

        if not enough:
            overall = DriftStatus.COLLECTING
        else:
            measured = [row.psi for row in rows if row.psi is not None]
            # Общий статус — по худшему признаку, а не по среднему:
            # один уехавший признак среди двадцати семи усреднением
            # растворяется, а модели портит вход.
            overall = classify(max(measured)) if measured else DriftStatus.NOT_MEASURABLE

        return DriftReport(
            status=overall,
            observed_rows=observed_rows,
            baseline_rows=self._baseline.rows,
            baseline_generated_at=self._baseline.generated_at,
            model_trained_at=self._baseline.model_trained_at,
            min_observations=MIN_OBSERVATIONS,
            enough_data=enough,
            drifted=drifted,
            invalid_values=invalid,
            features=tuple(rows),
        )
