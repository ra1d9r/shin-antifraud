"""Пороги Risk Engine на работающей системе.

## Что настраивается на работающей системе

Три вещи, и все три — по одной причине: дашборд показывает, что они
дают, и после этого предлагать «поправьте `.env` и перезапустите прод»
было бы издевательством.

| Что | Адрес | Пункт брифинга |
|---|---|---|
| Пороги Risk Engine | `/config/thresholds` | §4.3 |
| Минимальные оценки политик | `/config/policies` | §4.5 «корректировать веса рисков» |
| Веса бизнес-метрики | `/config/cost` | §5.C «гибкая настраиваемая бизнес-метрика» |

Остальное — пути к артефактам, параметры датасета, настройки модели —
по-прежнему живёт в `.env` и требует перезапуска.

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

from app.api.deps import (
    SettingsDep,
    StateDep,
    apply_cost_weights,
    apply_policies,
    apply_thresholds,
)
from app.config.settings import Settings
from app.core.exceptions import ShinError
from app.i18n import DEFAULT_LANGUAGE, Language
from app.risk_engine.engine import RiskThresholds
from app.schemas.config import (
    AdaptiveThresholdsState,
    AdaptiveValidationOut,
    CostApplied,
    CostState,
    CostUpdate,
    PolicyApplied,
    PolicyOut,
    PolicyState,
    PolicyUpdate,
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


def require_admin(settings: Settings, token: str | None, what: str) -> None:
    """Пустить к записи или отказать.

    Вынесено, потому что проверку делают три эндпоинта. Пока она стояла
    в одном, скопировать её в новый и забыть половину было делом одной
    невнимательной минуты — а половина этой проверки открывает запись
    всем.
    """
    expected = settings.config_admin_token
    if not expected:
        raise ConfigLockedError(
            f"{what} выключена: не задан CONFIG_ADMIN_TOKEN. "
            "Адрес, которым можно отключить блокировки, без пароля открыт "
            "кому угодно, поэтому по умолчанию он закрыт."
        )
    if token != expected:
        raise ConfigLockedError(f"Неверный или отсутствующий заголовок {ADMIN_HEADER}.")


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
    require_admin(settings, x_admin_token, "Смена порогов")

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


# ------------------------------------------- политики (брифинг §4.5)


def _policy_state(
    state: StateDep,
    settings: Settings,
    language: Language = DEFAULT_LANGUAGE,
) -> PolicyState:
    engine = state.risk_engine
    return PolicyState(
        policies=[
            PolicyOut(
                key=rule.key,
                title=rule.title.get(language),
                min_score=rule.min_score,
                config_field=rule.config_field,
            )
            for rule in (engine.rules if engine else ())
        ],
        velocity_txn_per_hour=settings.rule_velocity_txn_per_hour,
        new_account_amount_ratio=settings.rule_new_account_amount_ratio,
        rules_enabled=engine.rules_enabled if engine else False,
        overridden=state.policies_overridden,
        changed_at=state.policy_changed_at,
        writable=bool(settings.config_admin_token),
    )


@router.get(
    "/config/policies",
    response_model=PolicyState,
    summary="Действующие пороги политик",
    description=(
        "С какой оценки каждая политика поднимает риск, и при каких "
        "условиях она вообще срабатывает.\n\n"
        "Читать открыто: те же значения видны в `POST /predict` "
        "у каждой сработавшей политики."
    ),
)
def read_policies(
    state: StateDep,
    settings: SettingsDep,
    language: Language = DEFAULT_LANGUAGE,
) -> PolicyState:
    return _policy_state(state, settings, language)


@router.post(
    "/config/policies",
    response_model=PolicyApplied,
    status_code=status.HTTP_200_OK,
    summary="Скорректировать веса рисков (брифинг §4.5)",
    description=(
        "Меняет минимальные оценки политик без перезапуска. Незаданные "
        "поля остаются как есть.\n\n"
        "| Что | Что с ним делается |\n"
        "|---|---|\n"
        "| Правила Risk Engine | пересобираются |\n"
        "| Теневое сравнение | обнуляется и пересобирается |\n"
        "| Аналитика дашборда | помечается устаревшей |\n"
        "| Наблюдение за дрейфом | **не трогается** |\n"
        "| История операций | сохраняется |\n\n"
        "Политики решают судьбу операции наравне с моделью, поэтому "
        "последствия те же, что у смены порогов, и по тем же причинам.\n\n"
        "**Требуется заголовок `X-Admin-Token`.**"
    ),
    responses={
        403: {"model": ErrorResponse, "description": "Не настроено или пароль не подошёл"},
        422: {"description": "Не задано ни одной величины или значение вне диапазона"},
    },
)
def update_policies(
    update: PolicyUpdate,
    state: StateDep,
    settings: SettingsDep,
    x_admin_token: Annotated[str | None, Header(alias=ADMIN_HEADER)] = None,
) -> PolicyApplied:
    require_admin(settings, x_admin_token, "Смена порогов политик")

    updates = update.model_dump(exclude={"changed_by", "reason"}, exclude_none=True)
    effects = apply_policies(
        state,
        updates=updates,
        changed_by=update.changed_by,
        reason=update.reason,
    )

    return PolicyApplied(
        state=_policy_state(state, state.settings, DEFAULT_LANGUAGE),
        changed=updates,
        **effects,
    )


# --------------------------------- бизнес-метрика стоимости (брифинг §5.C)


def _cost_state(state: StateDep, settings: Settings) -> CostState:
    curve = (state.evaluation or {}).get("curve", [])
    return CostState(
        fraud_loss_ratio=settings.cost_fraud_loss_ratio,
        fraud_fixed=settings.cost_fraud_fixed,
        false_block=settings.cost_false_block,
        false_challenge=settings.cost_false_challenge,
        overridden=state.cost_overridden,
        changed_at=state.cost_changed_at,
        writable=bool(settings.config_admin_token),
        curve_recomputable=bool(curve)
        and all(row.get("fraud_missed_amount") is not None for row in curve),
    )


@router.get(
    "/config/cost",
    response_model=CostState,
    summary="Действующие веса бизнес-метрики",
    description=(
        "Во что система оценивает пропущенный фрод и лишнее беспокойство "
        "клиента. Этими весами считаются кривая компромисса на дашборде "
        "и оптимальный порог."
    ),
)
def read_cost(state: StateDep, settings: SettingsDep) -> CostState:
    return _cost_state(state, settings)


@router.post(
    "/config/cost",
    response_model=CostApplied,
    status_code=status.HTTP_200_OK,
    summary="Настроить бизнес-метрику (брифинг §5.C)",
    description=(
        "Меняет веса метрики и **пересчитывает по ним кривую компромисса**. "
        "Незаданные поля остаются как есть.\n\n"
        "Решения не меняются: веса переводят уже принятые решения в деньги, "
        "а не участвуют в их принятии. Поэтому ни движок, ни тень "
        "не трогаются — меняется то, как система себя оценивает, "
        "а не то, как она судит.\n\n"
        "Аналитика не помечается устаревшей, а пересчитывается на месте: "
        "датасет для этого не нужен, в каждой точке кривой уже лежат "
        "счётчики и сумма пропущенного фрода.\n\n"
        "Если отчёт выгружен старой версией и сумм не хранит, ответ "
        "скажет `curve_recomputed: false` — числа на дашборде останутся "
        "посчитанными прежними весами, и об этом будет известно.\n\n"
        "**Требуется заголовок `X-Admin-Token`.**"
    ),
    responses={
        403: {"model": ErrorResponse, "description": "Не настроено или пароль не подошёл"},
        422: {"description": "Не задано ни одной величины или значение отрицательно"},
    },
)
def update_cost(
    update: CostUpdate,
    state: StateDep,
    settings: SettingsDep,
    x_admin_token: Annotated[str | None, Header(alias=ADMIN_HEADER)] = None,
) -> CostApplied:
    require_admin(settings, x_admin_token, "Настройка бизнес-метрики")

    updates = update.model_dump(exclude={"changed_by", "reason"}, exclude_none=True)
    effects = apply_cost_weights(
        state,
        updates=updates,
        changed_by=update.changed_by,
        reason=update.reason,
    )

    return CostApplied(
        state=_cost_state(state, state.settings),
        changed=updates,
        **effects,
    )
