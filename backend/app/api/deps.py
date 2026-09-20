"""Зависимости FastAPI: единое место сборки объектов приложения.

Модель загружается один раз при старте (ТЗ §5), а не на каждый запрос:
чтение артефакта и построение SHAP-explainer занимают заметное время.

Состояние держится в объекте `AppState`, который создаётся в lifespan
и кладётся в `app.state`. Тесты могут собрать свой экземпляр и подменить
его, не трогая глобальных переменных.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Annotated

from fastapi import Depends, Request

from app.analytics.report import load_report
from app.config.settings import Settings, get_settings
from app.core.exceptions import ModelNotLoadedError, ShinError
from app.core.logging import get_logger
from app.ml.pipeline import TrainedModel, load_model
from app.monitoring.drift import BaselineNotFoundError, DriftMonitor, load_baseline
from app.risk_engine.engine import RiskEngine
from app.services.prediction_service import PredictionService
from app.store.feedback import FeedbackStore
from app.store.profiles import UserProfileStore
from app.store.transactions import TransactionStore
from app.xai.explainer import Explainer

logger = get_logger("shin.api.deps")


@dataclass(slots=True)
class AppState:
    """Всё, что живёт между запросами."""

    settings: Settings
    profiles: UserProfileStore
    transactions: TransactionStore
    # Разметка аналитика живёт рядом с транзакциями, но переживает
    # и вытеснение из буфера, и перезапуск: она пишется на диск.
    feedback: FeedbackStore
    model: TrainedModel | None = None
    risk_engine: RiskEngine | None = None
    explainer: Explainer | None = None
    service: PredictionService | None = None
    # Аналитика по датасету — готовый артефакт, а не расчёт на лету.
    # Её отсутствие приложению не мешает: дашборд получит 503 с командой.
    evaluation: dict | None = None
    evaluation_error: str | None = None
    # Артефакт посчитан на другой модели, чем загружена сейчас. Отчёт при
    # этом отдаётся — но с пометкой, иначе дашборд врал бы молча.
    evaluation_stale: bool = False
    evaluation_stale_reason: str | None = None
    # Наблюдение за сдвигом распределения. Без эталона приложение
    # работает как раньше — просто не видит дрейф и говорит об этом.
    drift: DriftMonitor | None = None
    drift_error: str | None = None
    model_error: str | None = None
    started_at: float = field(default_factory=time.monotonic)

    @property
    def model_loaded(self) -> bool:
        return self.model is not None

    @property
    def uptime_seconds(self) -> float:
        return time.monotonic() - self.started_at


def build_state(settings: Settings | None = None) -> AppState:
    """Собрать состояние приложения и загрузить модель.

    Отсутствие модели не мешает приложению подняться: `/health` честно
    сообщит `degraded`, а `/predict` вернёт 503 с понятным текстом.
    Падать на старте здесь неправильно — иначе невозможно будет даже
    узнать через API, что именно не так.
    """
    settings = settings or get_settings()
    state = AppState(
        settings=settings,
        profiles=UserProfileStore(),
        transactions=TransactionStore(capacity=settings.max_stored_transactions),
        feedback=FeedbackStore(path=settings.feedback_file),
    )

    # Метки читаются до модели: они от неё не зависят, а потерять их
    # из-за незагрузившейся модели было бы обиднее всего — это единственное
    # в системе, что нельзя пересчитать заново.
    state.feedback.load()

    state.risk_engine = RiskEngine.from_settings(settings)

    try:
        state.model = load_model(settings.model_file)
    except FileNotFoundError:
        state.model_error = (
            f"Файл модели не найден: {settings.model_file}. "
            "Выполните: python backend/scripts/train_model.py"
        )
    except Exception as exc:  # noqa: BLE001 — причина уходит в /health как есть
        state.model_error = f"Модель не загрузилась: {exc}"

    if state.model_error:
        logger.error("%s", state.model_error)
        return state

    logger.info(
        "Модель загружена: %s, признаков %s, калибровка %s",
        state.model.algorithm,
        len(state.model.feature_names),
        state.model.calibration_method,
    )

    _load_evaluation(state)
    _load_drift_baseline(state)

    state.explainer = Explainer.from_model(
        state.model,
        prefer_shap=settings.xai_use_shap,
        top_factors=settings.xai_top_factors,
    )
    state.service = PredictionService(
        model=state.model,
        risk_engine=state.risk_engine,
        explainer=state.explainer,
        profiles=state.profiles,
        transactions=state.transactions,
        drift=state.drift,
    )
    return state


def _load_evaluation(state: AppState) -> None:
    """Прочитать артефакт аналитики и сверить его с загруженной моделью.

    Загружается после модели намеренно: сверять метку не с чем, пока модель
    не прочитана.

    Любая ошибка чтения гасится так же, как ошибка загрузки модели.
    Битый или недописанный JSON — не повод не поднять приложение: тогда
    нельзя было бы даже спросить у `/health`, что именно сломалось.
    """
    try:
        state.evaluation = load_report(state.settings.evaluation_file)
    except ShinError as exc:
        state.evaluation_error = exc.message
        logger.warning("%s", exc.message)
        return
    except Exception as exc:  # noqa: BLE001 — причина уходит в ответ как есть
        state.evaluation_error = (
            f"Аналитика не прочиталась ({exc}). "
            "Выгрузите заново: python backend/scripts/export_evaluation.py"
        )
        logger.error("%s", state.evaluation_error)
        return

    logger.info("Аналитика загружена: %s транзакций", state.evaluation.get("rows"))

    if state.model is None:
        return

    stamp = state.evaluation.get("model_trained_at")
    if stamp == state.model.trained_at:
        return

    state.evaluation_stale = True
    state.evaluation_stale_reason = (
        f"Аналитика посчитана на модели от {stamp or 'неизвестно когда'}, "
        f"а загружена модель от {state.model.trained_at}. "
        "Выгрузите заново: python backend/scripts/export_evaluation.py"
    )
    logger.warning("%s", state.evaluation_stale_reason)


def _load_drift_baseline(state: AppState) -> None:
    """Прочитать эталон распределения и завести наблюдение.

    Гасится так же, как всё остальное на старте: без эталона система
    работает ровно как прежде, только не видит дрейф. Падать здесь —
    значит из-за диагностики лишиться того, что она диагностирует.
    """
    try:
        baseline = load_baseline(state.settings.feature_baseline_file)
    except ShinError as exc:
        state.drift_error = exc.message
        logger.warning("%s", exc.message)
        return
    except Exception as exc:  # noqa: BLE001 — причина уходит в ответ как есть
        state.drift_error = (
            f"Эталон распределения не прочитался ({exc}). "
            "Выгрузите заново: python backend/scripts/export_evaluation.py"
        )
        logger.error("%s", state.drift_error)
        return

    state.drift = DriftMonitor(baseline)
    logger.info(
        "Эталон распределения загружен: %s признаков по %s строкам",
        len(baseline.features),
        baseline.rows,
    )


# ------------------------------------------------------------ зависимости


def get_state(request: Request) -> AppState:
    state = getattr(request.app.state, "shin", None)
    if state is None:  # pragma: no cover — возможно только при неверной сборке приложения
        raise ModelNotLoadedError("Состояние приложения не инициализировано")
    return state


def get_service(state: Annotated[AppState, Depends(get_state)]) -> PredictionService:
    """Сервис предсказаний. Без модели запрос завершается кодом 503."""
    if state.service is None:
        raise ModelNotLoadedError(
            state.model_error or "Модель не загружена — предсказания недоступны"
        )
    return state.service


def get_transactions(state: Annotated[AppState, Depends(get_state)]) -> TransactionStore:
    return state.transactions


def get_feedback(state: Annotated[AppState, Depends(get_state)]) -> FeedbackStore:
    """Хранилище разметки. Модель для него не нужна: метки — про прошлое."""
    return state.feedback


def get_drift(state: Annotated[AppState, Depends(get_state)]) -> DriftMonitor:
    """Наблюдение за дрейфом. Без эталона запрос завершается кодом 503."""
    if state.drift is None:
        raise BaselineNotFoundError(
            state.drift_error
            or (
                "Эталон распределения не выгружен. Выполните: "
                "python backend/scripts/export_evaluation.py"
            )
        )
    return state.drift


def get_app_settings(state: Annotated[AppState, Depends(get_state)]) -> Settings:
    return state.settings


StateDep = Annotated[AppState, Depends(get_state)]
ServiceDep = Annotated[PredictionService, Depends(get_service)]
TransactionsDep = Annotated[TransactionStore, Depends(get_transactions)]
FeedbackDep = Annotated[FeedbackStore, Depends(get_feedback)]
DriftDep = Annotated[DriftMonitor, Depends(get_drift)]
SettingsDep = Annotated[Settings, Depends(get_app_settings)]
