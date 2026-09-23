"""Вклады признаков в решение модели (ТЗ §7).

Модуль отвечает на один вопрос: насколько каждый признак сдвинул оценку
конкретной транзакции. Реализованы три способа, и выбирается лучший доступный.

| Движок | Что считает | Когда используется |
|---|---|---|
| `ShapTreeContributions` | точные значения Шепли по деревьям | установлен пакет `shap` |
| `LightGbmNativeContributions` | те же значения Шепли из самого LightGBM | модель LightGBM без `shap` |
| `AblationContributions` | изменение вероятности при замене признака на эталон | любая модель |

Два верхних движка объясняют **логит базовой модели до калибровки**.
Калибровка сигмоидой монотонна, поэтому порядок и знак вкладов сохраняются:
признак, повышающий логит, повышает и итоговый Risk Score. Абсолютные
величины при этом в единицах логита, а не вероятности, — это отражено
в поле `units` у результата.

`AblationContributions` наоборот работает с **итоговой калиброванной
вероятностью**: он подставляет вместо признака его эталонное значение
и смотрит, насколько изменилась вероятность. Метод грубее (не учитывает
взаимодействия признаков), зато объясняет ровно то число, из которого
считается Risk Score.
"""

from __future__ import annotations

import threading
import warnings
from dataclasses import dataclass
from typing import Any, Protocol

from app.core.logging import get_logger
from app.features.definitions import FEATURE_NAMES

logger = get_logger("shin.xai.contributions")


@dataclass(frozen=True, slots=True)
class ContributionResult:
    """Вклады признаков для одной транзакции."""

    values: dict[str, float]
    method: str
    # "logit" — вклад в логит базовой модели, "probability" — в вероятность.
    units: str
    base_value: float

    def top(self, limit: int) -> list[tuple[str, float]]:
        """Признаки с наибольшим вкладом по модулю."""
        ordered = sorted(self.values.items(), key=lambda item: abs(item[1]), reverse=True)
        return ordered[:limit]


class ContributionEngine(Protocol):
    """Общий интерфейс движков вкладов."""

    name: str
    units: str

    def contributions(self, features: dict[str, float]) -> ContributionResult: ...


# --------------------------------------------------------------- helpers


def unwrap_tree_model(estimator: Any) -> Any | None:
    """Достать базовую древесную модель из калиброванной обёртки.

    Модель сохраняется как `CalibratedClassifierCV -> FrozenEstimator -> LGBMClassifier`.
    SHAP умеет объяснять только само дерево, поэтому обёртки надо снять.
    Возвращает None, если внутри не дерево.
    """
    candidate = estimator

    for _ in range(5):  # защита от неожиданно глубокой вложенности
        calibrated = getattr(candidate, "calibrated_classifiers_", None)
        if calibrated:
            candidate = calibrated[0].estimator
            continue

        inner = getattr(candidate, "estimator", None)
        if inner is not None and inner is not candidate:
            candidate = inner
            continue

        break

    has_trees = hasattr(candidate, "booster_") or hasattr(candidate, "_predictors")
    return candidate if has_trees else None


def _as_row(features: dict[str, float]) -> list[float]:
    return [float(features[name]) for name in FEATURE_NAMES]


# ------------------------------------------------------------------ SHAP

# SHAP предупреждает о смене формата вывода для бинарного LightGBM. Оба
# формата обрабатываются в `_select_positive_class`, поэтому предупреждение —
# чистый шум, повторяющийся в каждом запросе.
_SHAP_OUTPUT_WARNING = ".*output has changed.*"

_WARNING_FILTER_LOCK = threading.Lock()


def _silence_shap_output_warning() -> None:
    """Погасить известное предупреждение SHAP — один раз на процесс.

    Раньше это делалось прямо в обработчике запроса через
    `warnings.catch_warnings()`. Менеджер снимает копию глобального списка
    фильтров на входе и восстанавливает её на выходе, а список — общий
    на весь процесс. При параллельных запросах выход одного потока
    откатывал состояние к моменту ДО входа другого: предупреждение
    прорывалось наружу, а чужие фильтры молча исчезали.

    Фильтр ставится один раз при создании движка — это происходит на старте
    приложения, в один поток. Путь запроса глобального состояния больше
    не трогает вовсе.

    Повторная установка не нужна и вредна (список фильтров рос бы), поэтому
    сверяемся с самим списком, а не с флагом: так функция остаётся верной
    и если фильтр кто-то снял — например, pytest, оборачивающий каждый тест
    в собственный `catch_warnings`.
    """
    with _WARNING_FILTER_LOCK:
        for _action, message, *_rest in warnings.filters:
            if message is not None and message.pattern == _SHAP_OUTPUT_WARNING:
                return
        warnings.filterwarnings("ignore", message=_SHAP_OUTPUT_WARNING)


class ShapTreeContributions:
    """Точные значения Шепли через `shap.TreeExplainer`."""

    name = "shap"
    units = "logit"

    def __init__(self, tree_model: Any) -> None:
        import shap

        _silence_shap_output_warning()
        self._explainer = shap.TreeExplainer(tree_model)

    def contributions(self, features: dict[str, float]) -> ContributionResult:
        import numpy as np

        row = np.asarray([_as_row(features)], dtype=float)
        raw = self._explainer.shap_values(row)
        values = self._select_positive_class(raw)

        expected = self._explainer.expected_value
        base = float(np.ravel(expected)[-1]) if np.ndim(expected) else float(expected)

        return ContributionResult(
            values={name: float(value) for name, value in zip(FEATURE_NAMES, values, strict=True)},
            method=self.name,
            units=self.units,
            base_value=base,
        )

    @staticmethod
    def _select_positive_class(raw: Any) -> Any:
        """Привести выход SHAP к вектору длины `len(FEATURE_NAMES)`.

        Форма ответа зависит от версии библиотеки и типа модели: бывает
        список из двух массивов (по классу), массив (1, n_features) и
        массив (1, n_features, n_classes). Обрабатываем все три.
        """
        import numpy as np

        if isinstance(raw, list):
            raw = raw[-1]

        array = np.asarray(raw)
        if array.ndim == 3:            # (samples, features, classes)
            return array[0, :, -1]
        if array.ndim == 2:            # (samples, features)
            return array[0]
        return array


# -------------------------------------------------------- LightGBM native


class LightGbmNativeContributions:
    """Значения Шепли, встроенные в сам LightGBM (`pred_contrib=True`).

    Даёт тот же результат, что и SHAP, но не требует внешнего пакета —
    поэтому объяснения остаются точными даже в минимальной установке.
    """

    name = "lightgbm_native"
    units = "logit"

    def __init__(self, tree_model: Any) -> None:
        self._model = tree_model

    def contributions(self, features: dict[str, float]) -> ContributionResult:
        import numpy as np

        row = np.asarray([_as_row(features)], dtype=float)
        raw = np.asarray(self._model.predict(row, pred_contrib=True))[0]

        # Последний элемент — базовое значение (ожидаемый логит).
        values = raw[:-1]
        base = float(raw[-1])

        return ContributionResult(
            values={name: float(value) for name, value in zip(FEATURE_NAMES, values, strict=True)},
            method=self.name,
            units=self.units,
            base_value=base,
        )


# -------------------------------------------------------------- ablation


class AblationContributions:
    """Вклад = изменение вероятности при замене признака на эталонный.

    Работает с любой моделью, включая калиброванную обёртку, и объясняет
    ровно ту вероятность, из которой считается Risk Score.

    Стоимость — по одному предсказанию на признак (27 вызовов). Для одной
    транзакции это доли миллисекунды, для батча метод не предназначен.
    """

    name = "ablation"
    units = "probability"

    def __init__(self, model: Any, baseline: dict[str, float]) -> None:
        self._model = model
        self._baseline = baseline

    def contributions(self, features: dict[str, float]) -> ContributionResult:
        import pandas as pd

        columns = list(FEATURE_NAMES)
        actual = {name: float(features[name]) for name in columns}

        # Эталон: медиана легальных транзакций. Если её нет в артефакте —
        # нули, что для флагов и есть «признак не поднят».
        reference = {name: float(self._baseline.get(name, 0.0)) for name in columns}

        # Одним батчем: исходная строка, полностью эталонная и по одной
        # строке на каждый заменённый признак.
        rows = [actual, reference]
        for name in columns:
            variant = dict(actual)
            variant[name] = reference[name]
            rows.append(variant)

        frame = pd.DataFrame(rows, columns=columns)
        probabilities = self._model.predict_proba(frame)[:, 1]

        actual_probability = float(probabilities[0])
        base_probability = float(probabilities[1])

        values = {
            name: actual_probability - float(probabilities[index + 2])
            for index, name in enumerate(columns)
        }

        return ContributionResult(
            values=values,
            method=self.name,
            units=self.units,
            base_value=base_probability,
        )


# ------------------------------------------------------------- фабрика


def build_contribution_engine(
    model: Any,
    *,
    prefer_shap: bool = True,
) -> ContributionEngine:
    """Выбрать лучший доступный движок вкладов.

    Args:
        model: обученная модель Shin (`TrainedModel`).
        prefer_shap: разрешено ли использовать SHAP (настройка `XAI_USE_SHAP`).
    """
    tree_model = unwrap_tree_model(model.estimator)

    if tree_model is not None and prefer_shap:
        try:
            engine = ShapTreeContributions(tree_model)
            logger.info("XAI: используется SHAP TreeExplainer")
            return engine
        except Exception as exc:  # noqa: BLE001 — любая причина ведёт к следующему варианту
            logger.warning("SHAP недоступен (%s), пробуем встроенный расчёт LightGBM", exc)

    if tree_model is not None and hasattr(tree_model, "booster_"):
        try:
            engine = LightGbmNativeContributions(tree_model.booster_)
            logger.info("XAI: используется встроенный расчёт вкладов LightGBM")
            return engine
        except Exception as exc:  # noqa: BLE001
            logger.warning("Встроенный расчёт LightGBM недоступен (%s)", exc)

    logger.info("XAI: используется метод замены на эталон (ablation)")
    return AblationContributions(model.estimator, getattr(model, "feature_baseline", {}) or {})
