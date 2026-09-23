"""Проверка работоспособности API (ТЗ §2.1)."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import StateDep
from app.schemas.system import HealthResponse, ModelInfo

router = APIRouter(tags=["system"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Проверка работоспособности",
    description=(
        "Возвращает `ok`, если модель загружена и система готова принимать "
        "транзакции, и `degraded`, если модель отсутствует. Во втором случае "
        "причина видна в `GET /model`."
    ),
)
def health(state: StateDep) -> HealthResponse:
    return HealthResponse(
        status="ok" if state.model_loaded else "degraded",
        app_name=state.settings.app_name,
        version=state.settings.app_version,
        environment=state.settings.environment,
        model_loaded=state.model_loaded,
        explainer_method=state.explainer.method if state.explainer else None,
        rules_enabled=state.settings.rules_enabled,
        transactions_processed=state.transactions.processed_total,
        uptime_seconds=round(state.uptime_seconds, 2),
    )


@router.get(
    "/model",
    response_model=ModelInfo,
    tags=["system"],
    summary="Сведения о загруженной модели",
    description="Алгоритм, метод калибровки и метрики качества на тестовой выборке.",
)
def model_info(state: StateDep) -> ModelInfo:
    if state.model is None:
        return ModelInfo(loaded=False)

    metrics = state.model.metrics or {}
    return ModelInfo(
        loaded=True,
        algorithm=state.model.algorithm,
        calibration_method=state.model.calibration_method,
        feature_count=len(state.model.feature_names),
        trained_at=state.model.trained_at,
        format_version=state.model.format_version,
        roc_auc=metrics.get("roc_auc"),
        pr_auc=metrics.get("pr_auc"),
        precision=metrics.get("precision"),
        recall=metrics.get("recall"),
        f1=metrics.get("f1"),
    )
