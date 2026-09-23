"""Оркестрация цепочки обработки транзакции (ТЗ §15).

```
TransactionRequest
      │  + профиль клиента
      ▼
TransactionInput ──► build_features ──► model.predict ──► RiskEngine
                                                               │
                                          Explainer ◄──────────┘
                                              │
                                     PredictionResponse
```

Сервис знает о признаках, модели, движке риска и объяснении — но ничего
не знает про HTTP. Роут вызывает один метод и сериализует результат.

Порядок двух последних шагов важен: профиль клиента обновляется **после**
того, как решение принято. Иначе текущая транзакция сама себя объявила бы
привычной, и признак «новое устройство» не сработал бы никогда.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

from app.core.exceptions import ModelNotLoadedError
from app.core.logging import get_logger
from app.features.builder import TransactionInput, build_features, ip_subnet
from app.features.definitions import get_spec, has_spec
from app.features.merchants import merchant_category
from app.i18n import DEFAULT_LANGUAGE, Language
from app.monitoring.drift import DriftMonitor
from app.monitoring.shadow import ShadowRunner
from app.risk_engine.engine import RiskEngine
from app.schemas.prediction import (
    ExplanationOut,
    PredictionResponse,
    RiskFactorOut,
    ThresholdsOut,
    TriggeredRuleOut,
)
from app.schemas.transaction import TransactionRequest
from app.store.profiles import UserProfile, UserProfileStore
from app.store.transactions import TopReason, TransactionRecord, TransactionStore
from app.xai.explainer import Explainer

logger = get_logger("shin.services.prediction")


def _utc_now() -> datetime:
    """Текущее время как наивный UTC — в этом виде живут все метки системы."""
    return datetime.now(UTC).replace(tzinfo=None)


def _top_reason(assessment, explanation) -> TopReason | None:
    """Главная причина решения — разложенной, а не строкой.

    Порядок тот же, что в `Explanation.reasons`: политики идут первыми,
    потому что они детерминированы и обычно и определяют решение.
    """
    if assessment.triggered_rules:
        return TopReason(rule_key=assessment.triggered_rules[0].key)

    factor = explanation.top_model_factor
    if factor is None:
        return None
    return TopReason(
        feature=factor.feature,
        value=factor.value,
        contribution=factor.contribution,
    )


class PredictionService:
    """Полная цепочка анализа транзакции."""

    def __init__(
        self,
        model,
        risk_engine: RiskEngine,
        explainer: Explainer,
        profiles: UserProfileStore,
        transactions: TransactionStore,
        drift: DriftMonitor | None = None,
        shadow: ShadowRunner | None = None,
    ) -> None:
        self._model = model
        self._risk_engine = risk_engine
        self._explainer = explainer
        self._profiles = profiles
        self._transactions = transactions
        # Необязательная зависимость: без выгруженного эталона наблюдение
        # не заводится, и сервис работает ровно как прежде.
        self._drift = drift
        # Тень тоже необязательна, и это принципиально: ответ на запрос
        # не зависит от неё ни одним полем. Если она сломается, клиент
        # этого не заметит.
        self._shadow = shadow

    def replace_risk_engine(self, engine: RiskEngine) -> None:
        """Подменить движок — пороги меняются на работающей системе.

        Присваивание атрибута атомарно, поэтому запрос, идущий прямо
        сейчас, досчитает на прежнем движке, а следующий возьмёт новый.
        Правка полей движка на месте дала бы запрос, увидевший новый
        `approve_max` со старым `challenge_max`.
        """
        self._risk_engine = engine

    def replace_shadow(self, shadow: ShadowRunner | None) -> None:
        """Подменить теневую конфигурацию.

        Нужно вместе с `replace_risk_engine`: при смене порогов тень
        пересобирается, и без этого сервис продолжал бы кормить прежний
        объект, а эндпоинт показывал бы новый — навсегда пустым.
        """
        self._shadow = shadow

    @property
    def explainer_method(self) -> str:
        return self._explainer.method

    def predict(
        self,
        request: TransactionRequest,
        language: Language = DEFAULT_LANGUAGE,
    ) -> PredictionResponse:
        """Проанализировать транзакцию и вернуть решение с объяснением.

        `language` влияет только на пояснения: решение, оценка и вектор
        признаков от языка не зависят и зависеть не могут. Проверяется
        тестом — иначе перевод однажды стал бы влиять на вердикт.
        """
        if self._model is None:
            raise ModelNotLoadedError(
                "Модель не загружена. Выполните: python backend/scripts/train_model.py"
            )

        started = time.perf_counter()

        timestamp = request.timestamp or _utc_now()
        profile = self._profiles.get(request.user_id)
        transaction = self._build_input(request, profile, timestamp)

        features = build_features(transaction)
        probability = self._model.predict_one(features)
        # Сегмент для адаптивного порога (брифинг §6). Категория берётся
        # из запроса, если клиент её прислал, иначе по справочнику
        # мерчантов — тем же, которым пользуется feature engineering.
        segment = request.merchant_category or merchant_category(request.merchant)
        assessment = self._risk_engine.assess(probability, features, segment=segment)
        explanation = self._explainer.explain(features, assessment, language)

        # Состояние меняем только после того, как ответ полностью посчитан.
        if request.persist:
            # Наблюдение за дрейфом учитывает только то, что система
            # признала реальной операцией. Режим «что если» сюда не
            # попадает: иначе десяток нажатий Analyze на одном сценарии
            # сдвинул бы картину сильнее, чем настоящий поток.
            if self._drift is not None:
                self._drift.observe(features)

            # Вторая конфигурация видит ту же операцию и выносит своё
            # решение. Оно никуда не уходит: ни в ответ, ни в историю,
            # ни в профиль клиента. Считаются только расхождения.
            if self._shadow is not None:
                self._shadow.observe(
                    primary=assessment,
                    shadow=self._shadow.assess(probability, features),
                    transaction_id=request.transaction_id,
                    user_id=request.user_id,
                    amount=request.amount,
                )

            self._profiles.record(
                request.user_id,
                amount=request.amount,
                country=request.country,
                device_id=request.device_id,
                ip_address=request.ip_address,
                timestamp=timestamp,
                latitude=request.latitude,
                longitude=request.longitude,
            )
            self._transactions.add(
                TransactionRecord(
                    transaction_id=request.transaction_id,
                    user_id=request.user_id,
                    timestamp=timestamp,
                    amount=request.amount,
                    country=request.country,
                    merchant=request.merchant,
                    device_id=request.device_id,
                    risk_score=assessment.risk_score,
                    model_score=assessment.model_score,
                    decision=assessment.decision,
                    risk_level=assessment.risk_level,
                    triggered_rules=tuple(rule.key for rule in assessment.triggered_rules),
                    top_reason=_top_reason(assessment, explanation),
                    ip_subnet=ip_subnet(request.ip_address),
                )
            )

        elapsed_ms = (time.perf_counter() - started) * 1000.0

        return PredictionResponse(
            language=language,
            transaction_id=request.transaction_id,
            user_id=request.user_id,
            timestamp=timestamp,
            risk_score=assessment.risk_score,
            model_score=assessment.model_score,
            probability=assessment.probability,
            decision=assessment.decision,
            risk_level=assessment.risk_level,
            raised_by_rules=assessment.raised_by_rules,
            triggered_rules=[
                TriggeredRuleOut(
                    key=rule.key, title=rule.title.get(language), min_score=rule.min_score
                )
                for rule in assessment.triggered_rules
            ],
            explanation=ExplanationOut(
                method=explanation.method,
                units=explanation.units,
                base_value=explanation.base_value,
                summary=explanation.summary,
                reasons=list(explanation.reasons),
                model_reasons=list(explanation.model_reasons),
                policy_reasons=list(explanation.policy_reasons),
                factors=[
                    RiskFactorOut(
                        feature=factor.feature,
                        value=factor.value,
                        display_value=factor.display_value,
                        contribution=factor.contribution,
                        direction=factor.direction,
                        reason=factor.reason,
                        description=factor.description.get(language),
                    )
                    for factor in explanation.factors
                ],
            ),
            thresholds=ThresholdsOut(
                **assessment.thresholds.to_dict(),
                segment=assessment.segment,
            ),
            features={name: round(value, 6) for name, value in features.items()},
            processing_ms=round(elapsed_ms, 2),
        )

    # ------------------------------------------------------------ контекст

    @staticmethod
    def _build_input(
        request: TransactionRequest,
        profile: UserProfile | None,
        timestamp: datetime,
    ) -> TransactionInput:
        """Собрать вход feature engineering из запроса и профиля клиента.

        Приоритет: явное поле запроса, затем профиль, затем None —
        последнее означает «данных нет», и feature builder подставит
        нейтральное значение.
        """

        def pick(explicit, from_profile):
            return explicit if explicit is not None else from_profile

        known_devices = request.known_device_ids
        if known_devices is None:
            known_devices = list(profile.known_devices) if profile else []

        return TransactionInput(
            transaction_id=request.transaction_id,
            user_id=request.user_id,
            amount=request.amount,
            timestamp=timestamp,
            merchant=request.merchant,
            country=request.country,
            device_id=request.device_id,
            ip_address=request.ip_address,
            latitude=request.latitude,
            longitude=request.longitude,
            transaction_frequency=request.transaction_frequency,
            previous_transaction_amount=request.previous_transaction_amount,
            previous_transaction_country=request.previous_transaction_country,
            account_age_days=request.account_age_days,
            user_avg_amount=pick(
                request.user_avg_amount, profile.average_amount if profile else None
            ),
            user_amount_std=pick(
                request.user_amount_std, profile.amount_std if profile else None
            ),
            user_home_country=pick(
                request.user_home_country, profile.dominant_country if profile else None
            ),
            user_typical_frequency=pick(
                request.user_typical_frequency,
                profile.typical_daily_frequency if profile else None,
            ),
            known_device_ids=tuple(known_devices),
            previous_ip_address=pick(
                request.previous_ip_address, profile.previous_ip_address if profile else None
            ),
            previous_timestamp=pick(
                request.previous_timestamp, profile.previous_timestamp if profile else None
            ),
            previous_latitude=pick(
                request.previous_latitude, profile.previous_latitude if profile else None
            ),
            previous_longitude=pick(
                request.previous_longitude, profile.previous_longitude if profile else None
            ),
            # +1 включает саму текущую операцию. В обучающих данных счётчик
            # считался ПОСЛЕ добавления транзакции в ленту, поэтому его
            # минимум там равен единице и нулей нет вовсе. Профиль же
            # обновляется после принятия решения, и без +1 модель получала
            # бы на входе ноль — значение, которого не видела при обучении.
            txn_count_last_hour=pick(
                request.txn_count_last_hour,
                profile.count_recent(timestamp, hours=1) + 1 if profile else None,
            ),
            merchant_category=request.merchant_category,
        )


def retranslate(response: PredictionResponse, language: Language) -> PredictionResponse:
    """Перевести готовый ответ на другой язык, не считая его заново.

    Нужно для идемпотентного повтора. Ответ на повтор берётся из памяти
    и остался бы на языке первого запроса — а язык в отпечаток не входит
    и входить не должен: тогда тот же платёж, посланный по-казахски
    и по-английски, обработался бы дважды, удвоив историю и сдвинув
    профили. Ровно то, ради чего идемпотентность и заводилась.

    Пересобираются только тексты. Решение, оценка и вектор признаков
    берутся из исходного ответа нетронутыми — ответ на повтор обязан
    совпадать с первым, а не пересчитываться.
    """
    if response.language == language:
        return response

    factors = [
        factor.model_copy(
            update={
                "description": get_spec(factor.feature).description.get(language)
                if has_spec(factor.feature)
                else factor.description
            }
        )
        for factor in response.explanation.factors
    ]
    explanation = response.explanation.model_copy(update={"factors": factors})
    return response.model_copy(update={"language": language, "explanation": explanation})
