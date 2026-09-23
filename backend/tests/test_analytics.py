"""Тесты аналитики по датасету (брифинг §5.A, §11).

Проверяются инварианты, а не конкретные числа: числа меняются вместе
с моделью, а «остановленный плюс пропущенный фрод равен всему фроду»
верно всегда. Тест на конкретные значения пришлось бы править после
каждого переобучения, и его перестали бы читать.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.analytics.report import build_report, load_report
from app.config.settings import Settings
from app.main import create_app
from app.ml.dataset import generate_dataset
from app.ml.pipeline import prepare_training_data, train_model
from app.risk_engine.engine import RiskThresholds
from app.schemas.analytics import AnalyticsOverview

SEED = 314


@pytest.fixture(scope="module")
def report():
    """Отчёт на маленьком датасете: инварианты от размера не зависят."""
    settings = Settings()
    frame = generate_dataset(rows=6_000, users=250, fraud_rate=0.02, seed=SEED)
    features, labels = prepare_training_data(frame)
    model, _ = train_model(features, labels, random_state=SEED)

    return build_report(
        frame,
        features,
        labels,
        model.predict_proba(features),
        settings=settings,
        thresholds=RiskThresholds(
            approve_max=settings.risk_approve_max,
            challenge_max=settings.risk_challenge_max,
            critical_min=settings.risk_critical_min,
        ),
    )


# ------------------------------------------------------------- инварианты


def test_rows_add_up(report) -> None:
    """Каждая транзакция попала ровно в одну клетку разбивки."""
    assert report.fraud_rows + report.legit_rows == report.rows
    assert sum(row.legit + row.fraud for row in report.decisions) == report.rows


def test_fraud_is_either_stopped_or_missed(report) -> None:
    assert report.fraud_stopped + report.fraud_missed == report.fraud_rows
    assert report.fraud_blocked <= report.fraud_stopped


def test_friction_counts_only_legit(report) -> None:
    """Трение — это задетые добросовестные, а не все неодобренные."""
    not_approved_legit = sum(
        row.legit for row in report.decisions if row.decision != "APPROVE"
    )
    assert report.friction == not_approved_legit
    assert report.friction <= report.legit_rows


def test_shares_are_fractions(report) -> None:
    for share in (report.fraud_rate, report.fraud_stopped_share, report.friction_share):
        assert 0.0 <= share <= 1.0


# --------------------------------------------- спасённый бюджет (§5.A)


def test_saved_and_lost_money_add_up_to_everything_at_stake(report) -> None:
    """Каждая мошенническая операция либо остановлена, либо пропущена.

    Инвариант держит определение честным: если суммы разойдутся,
    значит часть фрода посчитана дважды или потеряна, и «спасённый
    бюджет» перестанет означать то, что написано на плитке.
    """
    assert report.fraud_loss_prevented + report.fraud_loss_incurred == pytest.approx(
        report.fraud_loss_exposure
    )


def test_saved_money_follows_the_same_formula_as_the_cost_model(report) -> None:
    """Иначе плитка и кривая считали бы одно разными правилами.

    Потери на текущем пороге по кривой — это ровно тот фрод, который
    ушёл с решением APPROVE. Совпадение не случайно: обе величины
    берут `amount * ratio + fixed` по одним и тем же операциям.
    """
    at_current = next(
        point for point in report.curve if point.threshold == report.thresholds["approve_max"]
    )

    assert report.fraud_loss_incurred == pytest.approx(at_current.fraud_loss)


def test_nothing_saved_when_everything_is_approved(report) -> None:
    """Вырожденный случай задаёт смысл шкалы: без системы спасено ноль."""
    exposure = report.fraud_loss_exposure
    no_system = next(point for point in report.curve if point.threshold == 100)

    assert no_system.fraud_loss == pytest.approx(exposure)


def test_saved_money_is_in_the_artifact(report) -> None:
    payload = report.to_dict()

    for field in ("fraud_loss_prevented", "fraud_loss_incurred", "fraud_loss_exposure"):
        assert field in payload, f"{field} нужен дашборду — брифинг §5.A"
        assert payload[field] >= 0


# ------------------------------------------------------------ кривая


def test_curve_covers_every_threshold(report) -> None:
    assert [point.threshold for point in report.curve] == list(range(101))


def test_curve_is_monotonic(report) -> None:
    """Поднимая порог, мы пропускаем больше фрода и трогаем меньше клиентов.

    Это свойство самой конструкции, а не данных: порог только переносит
    транзакции из одной группы в другую, и всегда в одну сторону.
    """
    missed = [point.fraud_missed for point in report.curve]
    friction = [point.friction for point in report.curve]

    assert missed == sorted(missed), "пропущенный фрод обязан расти с порогом"
    assert friction == sorted(friction, reverse=True), "трение обязано падать с порогом"


def test_curve_endpoints_are_degenerate(report) -> None:
    """На краях система вырождается: трогает почти всех или никого.

    При нулевом пороге пропущенный фрод не обязан быть нулевым: правило
    системы — `risk_score <= порог` одобряется, поэтому операция со счётом
    ровно 0 проходит и здесь. Важно, что это минимум по всей кривой.
    """
    strictest, loosest = report.curve[0], report.curve[100]

    assert strictest.fraud_missed == min(point.fraud_missed for point in report.curve)
    assert strictest.friction == max(point.friction for point in report.curve)
    assert loosest.friction == 0, "при пороге 100 не беспокоят никого"
    assert loosest.fraud_missed == report.fraud_rows


def test_optimal_threshold_is_the_cheapest(report) -> None:
    best = min(report.curve, key=lambda point: point.total_cost)
    assert report.optimal_threshold == best.threshold


def test_total_cost_is_the_sum_of_parts(report) -> None:
    for point in report.curve:
        assert point.total_cost == pytest.approx(point.fraud_loss + point.friction_cost)


# ------------------------------------------------------------- политики


def test_rule_marginal_contribution_is_consistent(report) -> None:
    """«Ноль пользы» и «цена за фрод» — одно и то же утверждение."""
    assert report.rules, "политики включены, статистика обязана быть"
    for rule in report.rules:
        assert 0.0 <= rule.precision <= 1.0
        if rule.gained_fraud == 0:
            assert rule.checks_per_fraud is None
        else:
            assert rule.checks_per_fraud == pytest.approx(
                rule.added_friction / rule.gained_fraud
            )


def test_policies_can_only_stop_more_than_the_model_alone(report) -> None:
    """Правила поднимают оценку и никогда не снижают.

    Значит ни один фрод и ни один честный клиент не могут выпасть из
    остановленных: множество решений, отличных от APPROVE, только растёт.
    Отрицательная разница означала бы, что где-то правило понизило балл.
    """
    assert report.fraud_stopped >= report.fraud_stopped_without_rules
    assert report.friction >= report.friction_without_rules
    assert report.rules_gained_fraud >= 0
    assert report.rules_added_friction >= 0


def test_counterfactual_shares_use_the_same_denominators(report) -> None:
    """Доли «без политик» сравнимы с обычными, иначе плитка врала бы."""
    assert report.fraud_stopped_share_without_rules == pytest.approx(
        report.fraud_stopped_without_rules / report.fraud_rows
    )
    assert report.friction_share_without_rules == pytest.approx(
        report.friction_without_rules / report.legit_rows
    )


def test_counterfactual_counts_come_from_the_same_run_as_the_counterfactual_cost(
    report,
) -> None:
    """Счётчики «без политик» и стоимость «без политик» — один и тот же прогон.

    Проверка нужна именно в таком виде. Если считать счётчики по решениям
    *с* политиками, разница выйдет нулевой — и это молча пройдёт все
    остальные утверждения: ноль неотрицателен и не больше суммы по
    строкам таблицы. Поймать подмену можно только противоречием со
    стоимостью, которая считается отдельно и по решениям без политик.

    Отсюда инвариант: стоимости разошлись тогда и только тогда, когда
    разошлись наборы решений.
    """
    costs_differ = report.cost_with_rules != report.cost_without_rules
    counts_differ = report.rules_gained_fraud > 0 or report.rules_added_friction > 0

    assert costs_differ == counts_differ


def test_policies_actually_move_the_numbers_on_this_dataset(report) -> None:
    """На этой выборке политики точно срабатывают — иначе сравнивать нечего.

    Файл уже опирается на это в `test_rule_marginal_contribution_is_consistent`.
    Здесь то же требование к сводке по слою: приписка «без политик» на
    плитках имеет смысл, только когда числа действительно разные.
    """
    assert report.rules_added_friction > 0
    assert report.friction_without_rules < report.friction


def test_the_whole_layer_is_not_the_sum_of_its_rules(report) -> None:
    """Сводка по слою считается по решениям, а не сложением строк таблицы.

    Политики пересекаются: на одной операции их срабатывает несколько,
    и каждая записывает себе её предельный вклад. Сумма по столбцу
    поэтому не меньше честной разницы — на этом и держится оговорка
    в интерфейсе.
    """
    assert report.rules_added_friction <= sum(rule.added_friction for rule in report.rules)
    assert report.rules_gained_fraud <= sum(rule.gained_fraud for rule in report.rules)


def test_geography_covers_the_dataset(report) -> None:
    """Карта аномалий (брифинг §6) считается по тем же решениям."""
    assert report.countries, "в датасете есть страны с известными координатами"

    for item in report.countries:
        assert item.rows > 0
        assert 0 <= item.fraud_rows <= item.rows
        assert 0 <= item.flagged <= item.rows
        assert -90 <= item.latitude <= 90
        assert -180 <= item.longitude <= 180

    # Сумма по странам не больше всего датасета: страны без известных
    # координат в карту не попадают, но лишних взяться неоткуда.
    assert sum(item.rows for item in report.countries) <= report.rows
    assert sum(item.fraud_rows for item in report.countries) <= report.fraud_rows


def test_countries_use_the_same_coordinates_as_the_features(report) -> None:
    """Второй набор координат разошёлся бы с тем, по которому считается
    скорость перемещения, и карта показывала бы не то место."""
    from app.features.geo import COUNTRY_COORDINATES

    for item in report.countries:
        assert item.country in COUNTRY_COORDINATES
        latitude, longitude = COUNTRY_COORDINATES[item.country]
        assert item.latitude == pytest.approx(latitude)
        assert item.longitude == pytest.approx(longitude)


def test_an_artifact_without_geography_still_serves(tmp_path) -> None:
    """Артефакт лежит файлом на диске и живёт дольше кода.

    Выгруженный до появления карты, он не содержит поля `countries`.
    Ронять из-за этого весь дашборд нельзя: карта — одна панель из
    одиннадцати, а отчёт нужен всем остальным.
    """
    payload = json.loads(
        (Path(__file__).resolve().parents[1] / "models" / "evaluation.json").read_text(
            encoding="utf-8"
        )
    )
    payload.pop("countries", None)

    overview = AnalyticsOverview(**payload)

    assert overview.countries == []
    assert overview.rows > 0, "остальной отчёт на месте"


def test_report_serialises_completely(report) -> None:
    """Отчёт должен пережить запись в JSON и чтение обратно."""
    payload = json.loads(json.dumps(report.to_dict(), ensure_ascii=False))

    assert payload["rows"] == report.rows
    assert len(payload["curve"]) == 101
    # Схема ответа API собирается из того же словаря — если она разойдётся
    # с отчётом, тест упадёт здесь, а не у жюри в браузере.
    AnalyticsOverview(**payload)


# ---------------------------------------------------------------- HTTP


@pytest.fixture(scope="module")
def client():
    with TestClient(create_app()) as test_client:
        yield test_client


def test_overview_endpoint_returns_report(client) -> None:
    response = client.get("/analytics/overview")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["rows"] > 0
    assert len(payload["curve"]) == 101


def test_committed_artifact_matches_configuration(client) -> None:
    """Выгруженный артефакт должен отвечать текущим настройкам.

    Ловит забытую перевыгрузку: пороги поменяли в `.env`, а `evaluation.json`
    остался от прежних. Дашборд показывал бы чужие числа.
    """
    settings = client.app.state.shin.settings
    payload = load_report(settings.evaluation_file)

    assert payload["thresholds"]["approve_max"] == settings.risk_approve_max
    assert payload["thresholds"]["challenge_max"] == settings.risk_challenge_max


def test_missing_artifact_reports_the_command(tmp_path) -> None:
    """Без артефакта приложение обязано подняться и назвать команду."""
    settings = Settings(evaluation_path=str(tmp_path / "нет.json"))
    with TestClient(create_app(settings)) as test_client:
        response = test_client.get("/analytics/overview")

    assert response.status_code == 503
    assert "export_evaluation" in response.json()["message"]


def test_broken_artifact_does_not_stop_the_application(tmp_path) -> None:
    """Битый JSON не должен мешать приложению подняться.

    Раньше `json.loads` бросал `JSONDecodeError`, а сборка состояния ловила
    только `ShinError` — приложение не стартовало вовсе, и спросить у него,
    что сломалось, было нельзя.
    """
    broken = tmp_path / "broken.json"
    broken.write_text("{это не json", encoding="utf-8")

    with TestClient(create_app(Settings(evaluation_path=str(broken)))) as test_client:
        assert test_client.get("/health").status_code == 200

        response = test_client.get("/analytics/overview")
        assert response.status_code == 503
        assert "export_evaluation" in response.json()["message"]


def test_artifact_from_another_model_is_marked_stale(tmp_path) -> None:
    """Отчёт от чужой модели отдаётся, но с пометкой.

    Молчаливое устаревание — самый дорогой класс ошибок в этом проекте:
    именно так метрики в README разошлись с моделью на три переобучения.
    Здесь дашборд обязан сказать об этом сам.
    """
    settings = Settings()
    payload = load_report(settings.evaluation_file)
    payload["model_trained_at"] = "1999-01-01T00:00:00"

    forged = tmp_path / "stale.json"
    forged.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with TestClient(create_app(Settings(evaluation_path=str(forged)))) as test_client:
        body = test_client.get("/analytics/overview").json()

    assert body["stale"] is True
    assert "1999-01-01" in body["stale_reason"]
    assert "export_evaluation" in body["stale_reason"]


def test_committed_artifact_matches_the_committed_model(client) -> None:
    """Выгруженный отчёт обязан относиться к той модели, что лежит рядом."""
    state = client.app.state.shin
    if state.model is None:
        pytest.skip("модель не загружена")

    assert state.evaluation["model_trained_at"] == state.model.trained_at, (
        "evaluation.json посчитан на другой модели. "
        "Выполните: python backend/scripts/export_evaluation.py"
    )
    assert state.evaluation_stale is False


def test_report_without_rules_has_no_rule_statistics() -> None:
    """При выключенных политиках отчёт не должен показывать их статистику.

    Раньше скрипт выгрузки всегда считал с политиками, и при
    `RULES_ENABLED=false` дашборд показывал бы работу правил, которых нет.
    """
    settings = Settings()
    frame = generate_dataset(rows=3_000, users=150, fraud_rate=0.02, seed=SEED)
    features, labels = prepare_training_data(frame)
    model, _ = train_model(features, labels, random_state=SEED)

    report = build_report(
        frame,
        features,
        labels,
        model.predict_proba(features),
        settings=settings,
        thresholds=RiskThresholds(
            approve_max=settings.risk_approve_max,
            challenge_max=settings.risk_challenge_max,
            critical_min=settings.risk_critical_min,
        ),
        model=model,
        rules_enabled=False,
    )

    assert report.rules == ()
    assert report.rules_enabled is False
    assert report.raised_by_rules == 0
    assert report.model_trained_at == model.trained_at

    # Без политик контрфактический расчёт совпадает с фактическим: сравнивать
    # не с чем, и интерфейс приписку «без политик» не показывает.
    assert report.fraud_stopped_without_rules == report.fraud_stopped
    assert report.friction_without_rules == report.friction
    assert report.rules_gained_fraud == 0
    assert report.rules_added_friction == 0


# ------------------------------- точность и полнота на кривой (§5.A)


def test_precision_and_recall_agree_with_the_counters(report) -> None:
    """Метрики выводятся из счётчиков, а не считаются вторым проходом.

    Если они разойдутся, значит кто-то завёл второй способ считать
    помеченное — и однажды два способа дадут разные числа на одной
    странице.
    """
    for point in report.curve:
        flagged = point.fraud_stopped + point.friction
        if flagged == 0:
            assert point.precision is None
        else:
            assert point.precision == pytest.approx(point.fraud_stopped / flagged)

        total_fraud = point.fraud_stopped + point.fraud_missed
        assert point.recall == pytest.approx(point.fraud_stopped / total_fraud)


def test_recall_falls_as_the_threshold_rises(report) -> None:
    """Свойство конструкции: поднимая порог, поймать больше нельзя.

    Про точность такого сказать нельзя — она может и просесть,
    поэтому её монотонность здесь намеренно не проверяется.
    """
    recalls = [point.recall for point in report.curve]

    assert recalls == sorted(recalls, reverse=True)


def test_metrics_stay_within_their_scale(report) -> None:
    for point in report.curve:
        for value in (point.precision, point.recall, point.f1):
            if value is not None:
                assert 0.0 <= value <= 1.0


def test_no_precision_when_nothing_is_flagged(report) -> None:
    """Ноль означал бы «всё помеченное оказалось честным» — другое утверждение."""
    loosest = report.curve[100]

    assert loosest.friction == 0 and loosest.fraud_stopped == 0
    assert loosest.precision is None
    assert loosest.recall == 0.0
    assert loosest.f1 is None


def test_f1_is_the_harmonic_mean(report) -> None:
    for point in report.curve:
        if point.precision and point.recall:
            expected = 2 * point.precision * point.recall / (point.precision + point.recall)
            assert point.f1 == pytest.approx(expected)


def test_trade_off_is_visible_in_one_point(report) -> None:
    """Ради чего пункт и делался: точность и потери лежат рядом.

    Брифинг §5.A просит «индикацию компромисса между точностью
    (Precision/Recall) и потерями бизнеса» — значит обе величины
    должны читаться из одной точки, а не из разных панелей.
    """
    cheapest = min(report.curve, key=lambda point: point.total_cost)
    # Самый строгий порог, на котором система ещё кого-то помечает.
    # Брать 99 жёстко нельзя: на маленькой выборке там уже никого нет,
    # точность неопределена, и тест падал бы от размера датасета,
    # а не от поведения системы.
    strictest = max(
        (point for point in report.curve if point.precision is not None),
        key=lambda point: point.threshold,
    )

    # Дешевле — значит больше ложных срабатываний. Это и есть компромисс.
    assert cheapest.precision < strictest.precision
    assert cheapest.recall > strictest.recall
    assert cheapest.total_cost < strictest.total_cost


def test_metrics_are_in_the_artifact(report) -> None:
    payload = report.to_dict()["curve"][0]

    for field in ("precision", "recall", "f1"):
        assert field in payload, f"{field} нужен дашборду — брифинг §5.A"
