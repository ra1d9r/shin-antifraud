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
from app.features.builder import TransactionInput, build_features
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
from app.store.transactions import TransactionRecord, TransactionStore
from app.xai.explainer import Explainer

logger = get_logger("shin.services.prediction")


def _utc_now() -> datetime:
    """Текущее время как наивный UTC — в этом виде живут все метки системы."""
    return datetime.now(UTC).replace(tzinfo=None)


class PredictionService:
    """Полная цепочка анализа транзакции."""

    def __init__(
        self,
        model,
        risk_engine: RiskEngine,
        explainer: Explainer,
        profiles: UserProfileStore,
        transactions: TransactionStore,
    ) -> None:
        self._model = model
        self._risk_engine = risk_engine
        self._explainer = explainer
        self._profiles = profiles
        self._transactions = transactions

    @property
    def explainer_method(self) -> str:
        return self._explainer.method

    def predict(self, request: TransactionRequest) -> PredictionResponse:
        """Проанализировать транзакцию и вернуть решение с объяснением."""
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
        assessment = self._risk_engine.assess(probability, features)
        explanation = self._explainer.explain(features, assessment)

        # Состояние меняем только после того, как ответ полностью посчитан.
        if request.persist:
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
                    top_reason=explanation.reasons[0] if explanation.reasons else None,
                )
            )

        elapsed_ms = (time.perf_counter() - started) * 1000.0

        return PredictionResponse(
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
                TriggeredRuleOut(key=rule.key, title=rule.title, min_score=rule.min_score)
                for rule in assessment.triggered_rules
            ],
            explanation=ExplanationOut(
                method=explanation.method,
                units=explanation.units,
                base_value=explanation.base_value,
                summary=explanation.summary,
                reasons=list(explanation.reasons),
                policy_reasons=list(explanation.policy_reasons),
                factors=[
                    RiskFactorOut(
                        feature=factor.feature,
                        value=factor.value,
                        display_value=factor.display_value,
                        contribution=factor.contribution,
                        direction=factor.direction,
                        reason=factor.reason,
                        description=factor.description,
                    )
                    for factor in explanation.factors
                ],
            ),
            thresholds=ThresholdsOut(**assessment.thresholds.to_dict()),
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
