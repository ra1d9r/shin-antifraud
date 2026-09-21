"""Пороги Risk Engine на работающей системе.

## Почему это не просто «поле в настройках»

Пороги — единственная бизнес-величина, которую разрешено менять без
перезапуска. Причина в том, что менять их **нужно**: дашборд показывает
кривую компромисса, теневой режим показывает, что дало бы переключение
на живом потоке, — и после этого предлагать «поправьте `.env`
и перезапустите прод» было бы издевательством.

Но смена порога — это не присваивание. От порогов зависит всё, что
система уже насчитала, и порядок приведения остального в согласие
описан в `apply_thresholds`.

## Почему запись закрыта паролем

Адресом, которым можно поставить `approve_max = 100`, отключается
блокировка любого мошенничества. У проекта есть публичный
демонстрационный стенд, поэтому эндпоинт записи выключен, пока
не задан `CONFIG_ADMIN_TOKEN`.

Это не аутентификация: один общий пароль не различает людей и не
отзывается по одному. Настоящей системе нужны учётные записи и журнал
действий — см. [D-20](../../../../docs/TZ.md#отклонения-и-решения).
Здесь закрыта дыра, а не решена задача.

Чтение открыто: знать действующие пороги полезно, и они и так видны
в каждом ответе `POST /predict`.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, status

from app.api.deps import SettingsDep, StateDep, apply_thresholds
from app.core.exceptions import ShinError
from app.risk_engine.engine import RiskThresholds
from app.schemas.config import (
    AdaptiveThresholdsState,
    AdaptiveValidationOut,
    SegmentThresholdOut,
    ThresholdChangeOut,
    ThresholdsApplied,
    ThresholdsState,
    ThresholdUpdate,
)
from app.schemas.system import ErrorResponse

router = APIRouter(tags=["config"])

ADMIN_HEADER = "X-Admin-Token"


class ConfigLockedError(ShinError):
    """Смена порогов не настроена или пароль не подошёл."""

    status_code = 403
    error_code = "config_locked"


def _state_out(state: StateDep, settings: SettingsDep) -> ThresholdsState:
    engine = state.risk_engine
    history = list(state.threshold_changes)
    return ThresholdsState(
        approve_max=engine.thresholds.approve_max,
        challenge_max=engine.thresholds.challenge_max,
        critical_min=engine.thresholds.critical_min,
        rules_enabled=engine.rules_enabled,
        overridden=state.thresholds_overridden,
        changed_at=history[0]["at"] if history else None,
        writable=bool(settings.config_admin_token),
        env_defaults={
            "approve_max": settings.risk_approve_max,
            "challenge_max": settings.risk_challenge_max,
            "critical_min": settings.risk_critical_min,
            "rules_enabled": settings.rules_enabled,
        },
        history=[ThresholdChangeOut(**item) for item in history],
    )


@router.get(
    "/config/thresholds",
    response_model=ThresholdsState,
    summary="Действующие пороги Risk Engine",
    description=(
        "Что применяется сейчас, откуда взялось и что вернёт перезапуск.\n\n"
        "`overridden: false` — работают значения из `.env`. Правки живут "
        "только в памяти: перезапуск всегда возвращает к `.env`, поэтому "
        "неудачную правку отменяет рестарт, а не поиск того, кто её сделал."
    ),
)
def current_thresholds(state: StateDep, settings: SettingsDep) -> ThresholdsState:
    return _state_out(state, settings)


@router.post(
    "/config/thresholds",
    response_model=ThresholdsApplied,
    status_code=status.HTTP_200_OK,
    summary="Сменить пороги на работающей системе",
    description=(
        "Меняет пороги без перезапуска и приводит за ними остальное.\n\n"
        "| Что | Что с ним делается |\n"
        "|---|---|\n"
        "| Теневое сравнение | обнуляется и пересобирается |\n"
        "| Аналитика дашборда | помечается устаревшей |\n"
        "| Наблюдение за дрейфом | **не трогается** |\n"
        "| История операций | сохраняется |\n\n"
        "Тень обнуляется потому, что сравнивает две конфигурации: если "
        "одна изменилась посреди набора, матрица смешивает разное. "
        "Дрейф не трогается потому, что сравнивает распределение входных "
        "признаков, а пороги на признаки не влияют вовсе — обнулить его "
        "значило бы выбросить исправные наблюдения за компанию.\n\n"
        "История операций сохраняется, но `GET /stats` теперь сообщает "
        "время последней смены: числа в нём охватывают две конфигурации.\n\n"
        "**Требуется заголовок `X-Admin-Token`.** Пока `CONFIG_ADMIN_TOKEN` "
        "не задан, эндпоинт выключен: адресом, которым можно поставить "
        "`approve_max = 100`, отключается блокировка любого мошенничества."
    ),
    responses={
        403: {"model": ErrorResponse, "description": "Не настроено или пароль не подошёл"},
        422: {"description": "Пороги не возрастают"},
    },
)
def update_thresholds(
    update: ThresholdUpdate,
    state: StateDep,
    settings: SettingsDep,
    x_admin_token: Annotated[str | None, Header(alias=ADMIN_HEADER)] = None,
) -> ThresholdsApplied:
    expected = settings.config_admin_token
    if not expected:
        raise ConfigLockedError(
            "Смена порогов выключена: не задан CONFIG_ADMIN_TOKEN. "
            "Адрес, которым можно отключить блокировки, без пароля открыт "
            "кому угодно, поэтому по умолчанию он закрыт."
        )
    if x_admin_token != expected:
        raise ConfigLockedError(f"Неверный или отсутствующий заголовок {ADMIN_HEADER}.")

    effects = apply_thresholds(
        state,
        thresholds=RiskThresholds(
            approve_max=update.approve_max,
            challenge_max=update.challenge_max,
            critical_min=update.critical_min,
        ),
        rules_enabled=update.rules_enabled,
        changed_by=update.changed_by,
        reason=update.reason,
    )

    return ThresholdsApplied(state=_state_out(state, settings), **effects)


@router.get(
    "/config/adaptive",
    response_model=AdaptiveThresholdsState,
    summary="Адаптивный порог по категории мерчанта",
    description=(
        "Бонус брифинга §6: «автоматическая подстройка чувствительности "
        "модели в зависимости от времени суток или категории мерчанта».\n\n"
        "Порог каждой категории подобран по той же функции стоимости, "
        "по которой строится кривая компромисса, — руками не назначен "
        "ни один. Интуиция здесь ошибается знаком: кажется, что у "
        "криптобирж и обменников порог надо опускать, а подобранный "
        "оказывается выше общего, потому что модель уже учитывает "
        "категорию признаком.\n\n"
        "Блок `validation` говорит, чего режим стоит. Проверка "
        "перекрёстная: порог сегмента подбирается без тех строк, "
        "на которых потом считается результат.\n\n"
        "Время суток тоже проверялось и в среднем **проигрывает**, "
        "поэтому сегментация только по категории. Брифинг говорит "
        "«времени суток или категории мерчанта», так что этого достаточно."
    ),
)
def adaptive_thresholds(state: StateDep) -> AdaptiveThresholdsState:
    thresholds = state.adaptive
    if thresholds is None:
        return AdaptiveThresholdsState(
            available=False, enabled=False, error=state.adaptive_error
        )

    return AdaptiveThresholdsState(
        available=True,
        # Применяются ли на самом деле, а не что написано в настройке:
        # движок мог быть пересобран сменой порогов в рантайме.
        enabled=state.risk_engine is not None and state.risk_engine.adaptive is not None,
        generated_at=thresholds.generated_at,
        rows=thresholds.rows,
        min_fraud_per_segment=thresholds.min_fraud_per_segment,
        fallback_approve_max=thresholds.fallback_approve_max,
        segments=[SegmentThresholdOut(**item.to_dict()) for item in thresholds.segments],
        validation=(
            None
            if thresholds.validation is None
            else AdaptiveValidationOut(**thresholds.validation.to_dict())
        ),
    )
