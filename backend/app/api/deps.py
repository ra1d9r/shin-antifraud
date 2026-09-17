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

from app.config.settings import Settings, get_settings
from app.core.exceptions import ModelNotLoadedError
from app.core.logging import get_logger
from app.ml.pipeline import TrainedModel, load_model
from app.risk_engine.engine import RiskEngine
from app.services.prediction_service import PredictionService
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
    model: TrainedModel | None = None
    risk_engine: RiskEngine | None = None
    explainer: Explainer | None = None
    service: PredictionService | None = None
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
    )

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
    )
    return state


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


def get_app_settings(state: Annotated[AppState, Depends(get_state)]) -> Settings:
    return state.settings


StateDep = Annotated[AppState, Depends(get_state)]
ServiceDep = Annotated[PredictionService, Depends(get_service)]
TransactionsDep = Annotated[TransactionStore, Depends(get_transactions)]
SettingsDep = Annotated[Settings, Depends(get_app_settings)]
