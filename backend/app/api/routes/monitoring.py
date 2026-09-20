"""Наблюдение за системой в работе: сдвиг распределения признаков.

Два наблюдения за системой в работе, и оба про то, чего не видно
по одной транзакции.

**Дрейф** сравнивает форму входных данных с той, на которой система
строилась. Ответа «правильно или нет» здесь нет вовсе: есть ответ
«похоже ли на то, что модель видела».

**Тень** прогоняет вторую конфигурацию по тем же операциям и считает,
что изменилось бы при переключении. Её решения никуда не уходят.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import DriftDep, ShadowDep
from app.schemas.monitoring import DriftReportOut, FeatureDriftOut
from app.schemas.shadow import (
    ConfigurationOut,
    DisagreementOut,
    MatrixCellOut,
    ShadowComparison,
)

router = APIRouter(tags=["monitoring"])


@router.get(
    "/monitoring/drift",
    response_model=DriftReportOut,
    summary="Сдвиг распределения признаков относительно обучающего",
    description=(
        "Population Stability Index по каждому признаку: насколько живой "
        "поток разошёлся с датасетом, на котором система строилась.\n\n"
        "Принятые границы — до 0.1 стабильно, 0.1–0.25 умеренный сдвиг, "
        "дальше существенный. Это отраслевая договорённость скоринга, "
        "а не выведенный из наших данных порог: повод посмотреть, "
        "а не приговор.\n\n"
        "Пока наблюдений меньше минимума, числа не называются — на "
        "полусотне транзакций PSI меряет случайность. Счётчики живут "
        "в памяти и обнуляются при перезапуске: в отличие от разметки "
        "аналитика, их восстанавливает обычный трафик.\n\n"
        "Режим «что если» (`persist=false`) в наблюдение не попадает."
    ),
    responses={503: {"description": "Эталон распределения не выгружен"}},
)
def drift_report(drift: DriftDep) -> DriftReportOut:
    report = drift.report()
    return DriftReportOut(
        status=report.status,
        observed_rows=report.observed_rows,
        baseline_rows=report.baseline_rows,
        baseline_generated_at=report.baseline_generated_at,
        model_trained_at=report.model_trained_at,
        min_observations=report.min_observations,
        enough_data=report.enough_data,
        drifted=report.drifted,
        invalid_values=report.invalid_values,
        features=[
            FeatureDriftOut(
                name=feature.name,
                description=feature.description,
                status=feature.status,
                psi=feature.psi,
                labels=list(feature.labels),
                expected=list(feature.expected),
                observed=list(feature.observed),
            )
            for feature in report.features
        ],
    )


@router.get(
    "/monitoring/shadow",
    response_model=ShadowComparison,
    summary="Теневая конфигурация: что было бы при других настройках",
    description=(
        "Вторая конфигурация Risk Engine видит те же настоящие операции "
        "и выносит свои решения. Они **никуда не уходят**: ответ "
        "`POST /predict` от них не зависит ни одним полем, в историю "
        "и в профиль клиента они не попадают, деньги по ним не "
        "блокируются. Считаются только расхождения.\n\n"
        "Отличие от кривой на дашборде: та отвечает, что было бы на "
        "обучающем датасете. Здесь — что происходит на сегодняшнем "
        "потоке, и переключение можно оценить заранее.\n\n"
        "Настраивается переменными `SHADOW_*`. По умолчанию тень "
        "проверяет самое неприятное открытие дашборда: те же пороги, "
        "но без политик поверх модели."
    ),
    responses={503: {"description": "Теневой режим выключен или настроен неверно"}},
)
def shadow_comparison(shadow: ShadowDep) -> ShadowComparison:
    report = shadow.report()
    return ShadowComparison(
        enabled=report.enabled,
        differs=report.differs,
        difference=report.difference,
        primary=ConfigurationOut(
            **report.primary_thresholds, rules_enabled=report.primary_rules_enabled
        ),
        shadow=ConfigurationOut(
            **report.shadow_thresholds, rules_enabled=report.shadow_rules_enabled
        ),
        observed=report.observed,
        agreed=report.agreed,
        disagreed=report.disagreed,
        agreement_share=report.agreement_share,
        freed_count=report.freed_count,
        freed_amount=report.freed_amount,
        tightened_count=report.tightened_count,
        tightened_amount=report.tightened_amount,
        matrix=[
            MatrixCellOut(
                primary=cell.primary, shadow=cell.shadow, count=cell.count, amount=cell.amount
            )
            for cell in report.matrix
        ],
        recent=[
            DisagreementOut(
                transaction_id=item.transaction_id,
                user_id=item.user_id,
                amount=item.amount,
                primary_decision=item.primary_decision,
                primary_score=item.primary_score,
                shadow_decision=item.shadow_decision,
                shadow_score=item.shadow_score,
                at=item.at,
            )
            for item in report.recent
        ],
    )
