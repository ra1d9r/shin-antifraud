"""Зависимости FastAPI: единое место сборки объектов приложения.

Модель загружается один раз при старте (ТЗ §5), а не на каждый запрос:
чтение артефакта и построение SHAP-explainer занимают заметное время.

Состояние держится в объекте `AppState`, который создаётся в lifespan
и кладётся в `app.state`. Тесты могут собрать свой экземпляр и подменить
его, не трогая глобальных переменных.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, Request

from app.analytics.report import cheapest_threshold, load_report, reprice_curve
from app.config.settings import Settings, get_settings
from app.core.exceptions import ModelNotLoadedError, ShadowUnavailableError, ShinError
from app.core.logging import get_logger
from app.ml.pipeline import TrainedModel, load_model
from app.monitoring.drift import BaselineNotFoundError, DriftMonitor, load_baseline
from app.monitoring.shadow import ShadowRunner
from app.risk_engine.adaptive import AdaptiveThresholds
from app.risk_engine.adaptive import load as load_adaptive
from app.risk_engine.engine import RiskEngine, RiskThresholds
from app.risk_engine.rules import build_rules
from app.services.prediction_service import PredictionService
from app.store.feedback import FeedbackStore
from app.store.idempotency import IdempotencyStore
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
    # Повторы POST /predict. Пустое хранилище при выключенной настройке:
    # проверять некому, и роут обработает запрос как обычно.
    idempotency: IdempotencyStore | None = None
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
    # Вторая конфигурация на том же потоке. Её решения никуда не уходят:
    # ответ API от неё не зависит ни одним полем.
    shadow: ShadowRunner | None = None
    shadow_error: str | None = None
    # Подобранные пороги по категориям мерчанта (брифинг §6). Артефакт
    # читается всегда, чтобы панель могла показать таблицу и измеренный
    # эффект; применяются они только при включённой настройке.
    adaptive: AdaptiveThresholds | None = None
    adaptive_error: str | None = None
    model_error: str | None = None
    # Правки порогов на работающей системе. Живут в памяти: перезапуск
    # возвращает к `.env`, и неудачную правку отменяет рестарт.
    threshold_changes: deque = field(default_factory=lambda: deque(maxlen=20))
    # Когда в последний раз правили политики и веса метрики. `None` —
    # не правили ни разу, действуют значения из `.env`. Хранится время,
    # а не флаг: «меняли» без «когда» не помогает разобраться, почему
    # числа выглядят иначе, чем вчера.
    policy_changed_at: datetime | None = None
    cost_changed_at: datetime | None = None
    started_at: float = field(default_factory=time.monotonic)

    @property
    def thresholds_overridden(self) -> bool:
        return bool(self.threshold_changes)

    @property
    def policies_overridden(self) -> bool:
        return self.policy_changed_at is not None

    @property
    def cost_overridden(self) -> bool:
        return self.cost_changed_at is not None

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
        idempotency=(
            IdempotencyStore(capacity=settings.max_idempotency_keys)
            if settings.idempotency_enabled
            else None
        ),
    )

    # Метки читаются до модели: они от неё не зависят, а потерять их
    # из-за незагрузившейся модели было бы обиднее всего — это единственное
    # в системе, что нельзя пересчитать заново.
    state.feedback.load()

    state.risk_engine = RiskEngine.from_settings(settings)
    _build_shadow(state)

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
    _load_adaptive_thresholds(state)

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
        shadow=state.shadow,
    )
    return state


def _build_shadow(state: AppState) -> None:
    """Собрать теневую конфигурацию.

    Гасится как всё остальное на старте: кривые пороги в `.env` не должны
    ронять приложение. Тень — инструмент наблюдения, и лишиться из-за него
    работающей системы было бы обменом в неверную сторону.
    """
    if not state.settings.shadow_enabled:
        state.shadow_error = "Теневой режим выключен настройкой SHADOW_ENABLED."
        return
    if state.risk_engine is None:  # pragma: no cover — движок строится выше
        return

    try:
        state.shadow = ShadowRunner.from_settings(state.settings, state.risk_engine)
    except ShinError as exc:
        state.shadow_error = f"Теневая конфигурация некорректна: {exc.message}"
        logger.warning("%s", state.shadow_error)
        return

    if state.shadow.differs:
        logger.info("Теневая конфигурация: %s", state.shadow.report().difference)
    else:
        # Не ошибка: так бывает, когда тень ещё не настроили. Но и сравнивать
        # нечего, и панель должна сказать это словами, а не показывать
        # стопроцентное согласие как достижение.
        logger.warning("Теневая конфигурация совпадает с основной — сравнивать нечего")


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


def analytics_drift(state: AppState) -> str | None:
    """Разошёлся ли отчёт с настройками, которые действуют сейчас.

    Возвращает причину расхождения или `None`, если отчёт посчитан ровно
    на том, что работает.

    ## Почему сверка, а не флаг

    Раньше это был флаг: любая правка порогов поднимала его навсегда.
    Вернуть значения обратно было нельзя — отчёт, снова совпадающий
    с настройками до последнего числа, продолжал числиться устаревшим
    до перезапуска. На публичном стенде это означало, что достаточно
    один раз подвигать ползунок, и дашборд до конца дня встречает
    посетителя красным предупреждением, которое уже неправда.

    Сверка отвечает на честный вопрос: посчитан ли отчёт на том, что
    действует сейчас. Подвигали и вернули — расхождения нет.

    ## Что сравнивается

    Всё, чем `POST /config/*` может изменить решения: три порога Risk
    Engine, признак «применять политики», минимальные оценки каждой
    политики и параметры их срабатывания. Веса бизнес-метрики сюда
    не входят намеренно — они не меняют ни одного решения, а кривую
    стоимости пересчитывают на месте.

    Старый артефакт, не знающий про `rule_params`, по ним и не
    сверяется: расхождением считается несовпадение, а не отсутствие.
    """
    report = state.evaluation
    engine = state.risk_engine
    if report is None or engine is None:
        return None

    recorded = report.get("thresholds") or {}
    live = engine.thresholds
    for name, value in (
        ("approve_max", live.approve_max),
        ("challenge_max", live.challenge_max),
        ("critical_min", live.critical_min),
    ):
        if name in recorded and recorded[name] != value:
            return (
                f"Порог {name} изменён на работающей системе: в отчёте "
                f"{recorded[name]}, сейчас {value}. Выгрузите заново: "
                "python backend/scripts/export_evaluation.py"
            )

    if "rules_enabled" in report and bool(report["rules_enabled"]) != engine.rules_enabled:
        return (
            "Применение политик переключено на работающей системе, "
            "а отчёт посчитан на прежней настройке. Выгрузите заново: "
            "python backend/scripts/export_evaluation.py"
        )

    recorded_rules = {row["key"]: row["min_score"] for row in report.get("rules", [])}
    for rule in engine.rules:
        if rule.key in recorded_rules and recorded_rules[rule.key] != rule.min_score:
            return (
                f"Минимум политики {rule.key} изменён на работающей системе: "
                f"в отчёте {recorded_rules[rule.key]}, сейчас {rule.min_score}. "
                "Выгрузите заново: python backend/scripts/export_evaluation.py"
            )

    recorded_params = report.get("rule_params") or {}
    live_params = {
        "velocity_txn_per_hour": float(state.settings.rule_velocity_txn_per_hour),
        "new_account_amount_ratio": float(state.settings.rule_new_account_amount_ratio),
    }
    for name, value in live_params.items():
        if name in recorded_params and float(recorded_params[name]) != value:
            return (
                f"Параметр политик {name} изменён на работающей системе: "
                f"в отчёте {recorded_params[name]}, сейчас {value}. "
                "Выгрузите заново: python backend/scripts/export_evaluation.py"
            )

    return None


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


def _load_adaptive_thresholds(state: AppState) -> None:
    """Прочитать подобранные пороги и, если разрешено, включить их.

    Гасится как всё остальное на старте: без артефакта система работает
    на одном пороге для всех операций — ровно как до появления режима.

    Таблица читается независимо от настройки: панель показывает
    измеренный эффект и выключенного режима тоже, иначе решение
    «включать или нет» было бы вслепую.
    """
    try:
        thresholds = load_adaptive(state.settings.adaptive_thresholds_file)
    except ShinError as exc:
        state.adaptive_error = exc.message
        logger.warning("%s", exc.message)
        return
    except Exception as exc:  # noqa: BLE001 — причина уходит в ответ как есть
        state.adaptive_error = (
            f"Адаптивные пороги не прочитались ({exc}). "
            "Выгрузите заново: python backend/scripts/export_evaluation.py"
        )
        logger.error("%s", state.adaptive_error)
        return

    state.adaptive = thresholds
    if state.settings.adaptive_thresholds_enabled and state.risk_engine is not None:
        state.risk_engine.adaptive = thresholds
        logger.info(
            "Адаптивный порог включён: сегментов %s, общий запасной %s",
            len(thresholds.segments),
            thresholds.fallback_approve_max,
        )
    else:
        logger.info(
            "Адаптивный порог подобран (%s сегментов), но выключен настройкой",
            len(thresholds.segments),
        )


def apply_thresholds(
    state: AppState,
    *,
    thresholds: RiskThresholds,
    rules_enabled: bool,
    changed_by: str | None = None,
    reason: str | None = None,
) -> dict:
    """Сменить пороги на работающей системе и привести за ними остальное.

    Порядок здесь важнее самой смены. Пороги меняют не одно число:
    от них зависит всё, что система уже успела насчитать.

    **Движок заменяется целиком, а не правится по полю.** `RiskThresholds`
    неизменяем, и подмена одного объекта на другой атомарна: запрос,
    идущий прямо сейчас, увидит либо старую конфигурацию, либо новую,
    но никогда половину одной и половину другой.

    **Теневое сравнение обнуляется.** Оно сравнивает две конфигурации;
    если одна изменилась посреди набора, матрица смешивает разное
    и перестаёт что-либо означать.

    **Тень пересобирается.** Незаданные пороги она наследует у основной —
    значит после смены основной наследование надо вывести заново, иначе
    тень осталась бы отличаться не тем, чем задумано.

    **Аналитика помечается устаревшей.** Она посчитана на прежних порогах.
    Тот же механизм, что при смене модели: скрывать числа хуже, чем
    показать их с пометкой.

    **Дрейф НЕ сбрасывается.** Он сравнивает распределение входных
    признаков с обучающим, а пороги на признаки не влияют вовсе.
    Обнулить его значило бы выбросить исправные наблюдения за компанию.
    """
    state.risk_engine = RiskEngine(
        thresholds=thresholds,
        rules=build_rules(state.settings),
        rules_enabled=rules_enabled,
    )
    if state.service is not None:
        state.service.replace_risk_engine(state.risk_engine)

    shadow_reset = False
    if state.shadow is not None:
        _build_shadow(state)
        # Сервису надо отдать именно новый объект: он держит ссылку,
        # а не читает состояние. Без этого тень замолчала бы навсегда —
        # сервис кормил бы прежний runner, а эндпоинт показывал новый.
        if state.service is not None:
            state.service.replace_shadow(state.shadow)
        shadow_reset = True

    # Отчёт не помечается, а сверяется — уже с новыми порогами.
    # Если ими вернули то, что было, расхождения нет, и ответ скажет
    # честное «нет», а не «пометил навсегда».
    marked_stale = analytics_drift(state) is not None

    state.threshold_changes.appendleft(
        {
            "at": datetime.now(UTC).replace(tzinfo=None),
            "approve_max": thresholds.approve_max,
            "challenge_max": thresholds.challenge_max,
            "critical_min": thresholds.critical_min,
            "rules_enabled": rules_enabled,
            "changed_by": changed_by,
            "reason": reason,
        }
    )
    logger.warning(
        "Пороги изменены в рантайме: APPROVE <= %s < CHALLENGE <= %s, политики %s (%s)",
        thresholds.approve_max,
        thresholds.challenge_max,
        "включены" if rules_enabled else "выключены",
        changed_by or "без подписи",
    )

    return {"shadow_reset": shadow_reset, "analytics_marked_stale": marked_stale}


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


def get_shadow(state: Annotated[AppState, Depends(get_state)]) -> ShadowRunner:
    """Теневая конфигурация. Без неё запрос завершается кодом 503."""
    if state.shadow is None:
        raise ShadowUnavailableError(
            state.shadow_error or "Теневой режим недоступен"
        )
    return state.shadow


def get_idempotency(
    state: Annotated[AppState, Depends(get_state)],
) -> IdempotencyStore | None:
    """Хранилище повторов. `None` — идемпотентность выключена настройкой."""
    return state.idempotency


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
IdempotencyDep = Annotated["IdempotencyStore | None", Depends(get_idempotency)]
DriftDep = Annotated[DriftMonitor, Depends(get_drift)]
ShadowDep = Annotated[ShadowRunner, Depends(get_shadow)]
SettingsDep = Annotated[Settings, Depends(get_app_settings)]


# ------------------------------------ настройка политик и бизнес-метрики


#: Поле запроса -> поле настроек. Имена в API короче: префикс `rule_`
#: там лишний, адрес и так называется `/config/policies`.
POLICY_FIELDS: dict[str, str] = {
    "impossible_travel_min_score": "rule_impossible_travel_min_score",
    "high_risk_country_min_score": "rule_high_risk_country_min_score",
    "unusual_country_min_score": "rule_unusual_country_min_score",
    "new_device_min_score": "rule_new_device_min_score",
    "velocity_min_score": "rule_velocity_min_score",
    "new_account_amount_min_score": "rule_new_account_amount_min_score",
    "velocity_txn_per_hour": "rule_velocity_txn_per_hour",
    "new_account_amount_ratio": "rule_new_account_amount_ratio",
}

COST_FIELDS: dict[str, str] = {
    "fraud_loss_ratio": "cost_fraud_loss_ratio",
    "fraud_fixed": "cost_fraud_fixed",
    "false_block": "cost_false_block",
    "false_challenge": "cost_false_challenge",
}


def apply_policies(
    state: AppState,
    *,
    updates: dict[str, float],
    changed_by: str | None = None,
    reason: str | None = None,
) -> dict:
    """Сменить пороги политик на работающей системе.

    Политики решают судьбу операции наравне с моделью, поэтому
    последствия те же, что у смены порогов Risk Engine, и по тем же
    причинам: тень обнуляется — она сравнивает две конфигурации;
    аналитика помечается устаревшей — её числа посчитаны на прежних
    политиках; дрейф не трогается — политики на входные признаки
    не влияют.

    Настройки заменяются целиком новым объектом, а не правятся по полю:
    `build_rules` читает их при сборке, и подмена одного объекта
    на другой не оставляет промежуточного состояния, в котором половина
    правил собрана по старым значениям.
    """
    state.settings = state.settings.model_copy(
        update={POLICY_FIELDS[name]: value for name, value in updates.items()}
    )

    engine = state.risk_engine
    state.risk_engine = RiskEngine(
        thresholds=engine.thresholds if engine else RiskThresholds(),
        rules=build_rules(state.settings),
        rules_enabled=engine.rules_enabled if engine else True,
    )
    if state.service is not None:
        state.service.replace_risk_engine(state.risk_engine)

    shadow_reset = False
    if state.shadow is not None:
        _build_shadow(state)
        if state.service is not None:
            state.service.replace_shadow(state.shadow)
        shadow_reset = True

    marked_stale = analytics_drift(state) is not None

    state.policy_changed_at = datetime.now(UTC).replace(tzinfo=None)
    logger.warning(
        "Пороги политик изменены в рантайме: %s (%s)",
        ", ".join(f"{name}={value}" for name, value in sorted(updates.items())),
        changed_by or "без подписи",
    )
    if reason:
        logger.warning("Причина смены политик: %s", reason)

    return {"shadow_reset": shadow_reset, "analytics_marked_stale": marked_stale}


def apply_cost_weights(
    state: AppState,
    *,
    updates: dict[str, float],
    changed_by: str | None = None,
    reason: str | None = None,
) -> dict:
    """Сменить веса бизнес-метрики и пересчитать по ним кривую.

    В отличие от политик, веса не влияют на решения: они переводят уже
    принятые решения в деньги. Поэтому ни тень, ни движок здесь
    не трогаются — меняется то, как система себя оценивает, а не то,
    как она судит.

    Аналитика не помечается устаревшей, а **пересчитывается**. Пометить
    её было бы проще, но бесполезно: человек, настраивающий метрику,
    хочет увидеть новый оптимум сразу, а не после выгрузки, которой
    в проде нечем заняться — датасета в образе нет. Пересчёт по счётчикам
    датасета не требует (см. `reprice_curve`).
    """
    state.settings = state.settings.model_copy(
        update={COST_FIELDS[name]: value for name, value in updates.items()}
    )
    state.cost_changed_at = datetime.now(UTC).replace(tzinfo=None)

    before = after = None
    recomputed = False
    if state.evaluation is not None:
        before = state.evaluation.get("optimal_threshold")
        curve = reprice_curve(state.evaluation.get("curve", []), state.settings)
        if curve is not None:
            state.evaluation = {
                **state.evaluation,
                "curve": curve,
                "optimal_threshold": cheapest_threshold(curve),
            }
            after = state.evaluation["optimal_threshold"]
            recomputed = True

    logger.warning(
        "Веса бизнес-метрики изменены в рантайме: %s (%s)",
        ", ".join(f"{name}={value}" for name, value in sorted(updates.items())),
        changed_by or "без подписи",
    )
    if reason:
        logger.warning("Причина смены весов: %s", reason)

    return {
        "curve_recomputed": recomputed,
        "optimal_threshold_before": before,
        "optimal_threshold_after": after,
    }
