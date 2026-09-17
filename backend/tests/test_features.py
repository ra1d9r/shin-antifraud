"""Тесты feature engineering (ТЗ §4).

Главный тест здесь — `test_batch_matches_single_row`: он проверяет, что
обучение и инференс считают признаки одинаково. Расхождение между ними
(training/serving skew) — самая дорогая и самая незаметная ошибка в ML-системе.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from app.features.builder import TransactionInput, build_features, build_feature_frame, build_feature_vector
from app.features.definitions import FEATURE_NAMES, FEATURE_SPECS, get_spec
from app.ml.dataset import generate_dataset

BASE_TIME = datetime(2026, 9, 1, 14, 30, 0)


def make_transaction(**overrides) -> TransactionInput:
    """Обычная транзакция знакомого клиента — точка отсчёта для всех тестов."""
    defaults = dict(
        transaction_id="txn_test_0001",
        user_id="user_test",
        amount=100.0,
        timestamp=BASE_TIME,
        merchant="Magnum",
        country="KZ",
        device_id="dev_known_1",
        ip_address="85.132.10.55",
        latitude=51.16,
        longitude=71.44,
        transaction_frequency=3,
        previous_transaction_amount=95.0,
        previous_transaction_country="KZ",
        account_age_days=800,
        user_avg_amount=100.0,
        user_amount_std=30.0,
        user_home_country="KZ",
        user_typical_frequency=3.0,
        known_device_ids=("dev_known_1", "dev_known_2"),
        previous_ip_address="85.132.10.40",
        previous_timestamp=BASE_TIME - timedelta(hours=5),
        previous_latitude=51.15,
        previous_longitude=71.40,
        txn_count_last_hour=1,
        merchant_category="grocery",
    )
    defaults.update(overrides)
    return TransactionInput(**defaults)


# --------------------------------------------------------------- реестр


def test_registry_names_are_unique() -> None:
    assert len(FEATURE_NAMES) == len(set(FEATURE_NAMES))


def test_every_spec_has_description_and_reason() -> None:
    for spec in FEATURE_SPECS:
        assert spec.description, f"{spec.name}: нет описания"
        assert spec.reason_high, f"{spec.name}: нет формулировки для XAI"


def test_features_match_registry_order() -> None:
    features = build_features(make_transaction())
    assert tuple(features.keys()) == FEATURE_NAMES
    assert len(build_feature_vector(make_transaction())) == len(FEATURE_NAMES)


# --------------------------------------------------- базовое поведение


def test_normal_transaction_has_no_red_flags() -> None:
    features = build_features(make_transaction())
    assert features["is_new_device"] == 0.0
    assert features["is_unusual_country"] == 0.0
    assert features["is_impossible_travel"] == 0.0
    assert features["is_night"] == 0.0
    assert features["is_high_frequency"] == 0.0
    assert features["amount_deviation_ratio"] == pytest.approx(1.0, abs=0.01)


def test_new_device_is_detected() -> None:
    features = build_features(make_transaction(device_id="dev_unknown_9"))
    assert features["is_new_device"] == 1.0


def test_empty_device_history_is_not_treated_as_new_device() -> None:
    """Первая в истории транзакция не должна считаться подозрительной."""
    features = build_features(make_transaction(known_device_ids=()))
    assert features["is_new_device"] == 0.0


def test_unusual_country_is_detected() -> None:
    features = build_features(make_transaction(country="NG"))
    assert features["is_unusual_country"] == 1.0
    assert features["country_changed_from_previous"] == 1.0
    assert features["is_high_risk_country"] == 1.0


def test_large_amount_raises_deviation_features() -> None:
    features = build_features(make_transaction(amount=2500.0))
    assert features["amount_deviation_ratio"] == pytest.approx(25.0, abs=0.1)
    assert features["amount_zscore"] > 10


def test_micro_amount_is_flagged() -> None:
    features = build_features(make_transaction(amount=2.0))
    assert features["is_micro_amount"] == 1.0


def test_high_frequency_is_detected() -> None:
    features = build_features(make_transaction(transaction_frequency=30))
    assert features["frequency_ratio"] == pytest.approx(10.0, abs=0.01)
    assert features["is_high_frequency"] == 1.0


def test_ip_change_is_detected() -> None:
    same_subnet = build_features(make_transaction(ip_address="85.132.10.90"))
    assert same_subnet["ip_changed"] == 1.0
    assert same_subnet["ip_subnet_changed"] == 0.0

    other_subnet = build_features(make_transaction(ip_address="203.0.113.5"))
    assert other_subnet["ip_subnet_changed"] == 1.0


def test_impossible_travel_is_detected() -> None:
    """Бразилия через 10 минут после Астаны — физически недостижимо."""
    features = build_features(
        make_transaction(
            latitude=-23.55,
            longitude=-46.63,
            country="BR",
            previous_timestamp=BASE_TIME - timedelta(minutes=10),
        )
    )
    assert features["is_impossible_travel"] == 1.0
    assert features["geo_distance_km"] > 10_000
    assert features["travel_speed_kmh"] > 900


def test_legitimate_travel_is_not_impossible() -> None:
    """Та же поездка, но за 20 часов — нормальный перелёт."""
    features = build_features(
        make_transaction(
            latitude=-23.55,
            longitude=-46.63,
            country="BR",
            previous_timestamp=BASE_TIME - timedelta(hours=20),
        )
    )
    assert features["is_impossible_travel"] == 0.0


def test_night_and_weekend_flags() -> None:
    night = build_features(make_transaction(timestamp=datetime(2026, 9, 1, 3, 0, 0)))
    assert night["is_night"] == 1.0
    assert night["hour_of_day"] == 3.0

    saturday = build_features(make_transaction(timestamp=datetime(2026, 9, 5, 14, 0, 0)))
    assert saturday["is_weekend"] == 1.0


def test_new_account_flag() -> None:
    assert build_features(make_transaction(account_age_days=10))["is_new_account"] == 1.0
    assert build_features(make_transaction(account_age_days=800))["is_new_account"] == 0.0


def test_high_risk_merchant_from_catalogue() -> None:
    """Категория определяется по названию мерчанта, если не передана явно."""
    features = build_features(make_transaction(merchant="Binance", merchant_category=None))
    assert features["is_high_risk_merchant"] == 1.0


# ------------------------------------------------- устойчивость к входу


def test_missing_context_does_not_crash() -> None:
    """Без профиля клиента признаки всё равно считаются."""
    features = build_features(
        make_transaction(
            user_avg_amount=None,
            user_amount_std=None,
            user_home_country=None,
            user_typical_frequency=None,
            known_device_ids=(),
            previous_ip_address=None,
            previous_timestamp=None,
            previous_latitude=None,
            previous_longitude=None,
            txn_count_last_hour=None,
            merchant_category=None,
        )
    )
    assert len(features) == len(FEATURE_NAMES)
    assert all(abs(value) < 1e12 for value in features.values())


def test_zero_previous_amount_does_not_divide_by_zero() -> None:
    features = build_features(make_transaction(previous_transaction_amount=0.0))
    assert features["amount_vs_previous_ratio"] < 1e6


def test_timezone_aware_timestamp_is_normalized() -> None:
    aware = make_transaction(timestamp=BASE_TIME.replace(tzinfo=timezone.utc))
    naive = make_transaction()
    assert build_features(aware)["hour_of_day"] == build_features(naive)["hour_of_day"]


def test_features_are_deterministic() -> None:
    transaction = make_transaction()
    assert build_features(transaction) == build_features(transaction)


# ----------------------------------------------- отсутствие skew (главное)


def test_batch_matches_single_row() -> None:
    """Батч-построение обязано совпадать с построчным до последнего знака."""
    frame = generate_dataset(rows=2_000, users=80, seed=11)
    batch = build_feature_frame(frame)

    from app.features.builder import transaction_from_row

    records = frame.to_dict(orient="records")
    for position in (0, 5, 100, 500, len(records) - 1):
        expected = build_features(transaction_from_row(records[position]))
        actual = batch.iloc[position].to_dict()
        for name in FEATURE_NAMES:
            assert actual[name] == pytest.approx(expected[name], rel=1e-12, abs=1e-12), (
                f"расхождение батча и одиночного расчёта в признаке {name}"
            )


def test_feature_frame_is_clean() -> None:
    frame = generate_dataset(rows=2_000, users=80, seed=12)
    matrix = build_feature_frame(frame)

    assert list(matrix.columns) == list(FEATURE_NAMES)
    assert not matrix.isna().to_numpy().any(), "в матрице признаков есть NaN"
    assert (matrix.abs() < 1e12).to_numpy().all(), "в матрице признаков есть бесконечности"


def test_changing_input_changes_features() -> None:
    """Ключевое требование ТЗ §15: результат обязан пересчитываться."""
    base = make_transaction()
    variants = {
        "device": replace(base, device_id="dev_new"),
        "country": replace(base, country="NG"),
        "amount": replace(base, amount=5000.0),
        "frequency": replace(base, transaction_frequency=40),
    }
    base_features = build_features(base)
    for label, variant in variants.items():
        assert build_features(variant) != base_features, f"{label}: признаки не изменились"


def test_spec_lookup_rejects_unknown_feature() -> None:
    with pytest.raises(KeyError):
        get_spec("no_such_feature")


# ------------------------------------------------------ регрессии на баги


def test_nat_previous_timestamp_does_not_produce_nan() -> None:
    """Регрессия: `pandas.NaT` — подкласс `datetime`.

    Проверка `isinstance(value, datetime)` его пропускала, арифметика давала
    NaT, и признак `hours_since_previous` становился NaN. NaN тихо разрушает
    и обучение, и предсказание.
    """
    from app.features.builder import transaction_from_row

    row = {
        "transaction_id": "t1", "user_id": "u1", "amount": 100.0,
        "timestamp": pd.Timestamp("2026-09-01 12:00:00"),
        "merchant": "Magnum", "country": "KZ", "device_id": "d1",
        "ip_address": "85.1.2.3", "latitude": 51.0, "longitude": 71.0,
        "transaction_frequency": 3, "previous_transaction_amount": 90.0,
        "previous_transaction_country": "KZ", "account_age_days": 500,
        "previous_timestamp": pd.NaT,
        "user_avg_amount": float("nan"),
    }
    transaction = transaction_from_row(row)
    assert transaction.previous_timestamp is None
    assert transaction.user_avg_amount is None

    features = build_features(transaction)
    assert all(value == value for value in features.values()), "в признаках появился NaN"


def test_non_datetime_timestamp_raises_clear_error() -> None:
    """Строка вместо даты должна давать понятную доменную ошибку."""
    from app.core.exceptions import FeatureBuildError

    with pytest.raises(FeatureBuildError, match="parse_dates"):
        build_features(make_transaction(timestamp="2026-09-01 12:00:00"))


def test_features_are_always_finite() -> None:
    """Вырожденные входы не должны давать inf или NaN."""
    extreme = make_transaction(
        amount=1e12,
        previous_transaction_amount=0.0,
        user_avg_amount=0.0,
        user_amount_std=0.0,
        user_typical_frequency=0.0,
        transaction_frequency=100_000,
        previous_timestamp=BASE_TIME,  # нулевой интервал
        previous_latitude=-89.0,
        previous_longitude=179.0,
        latitude=89.0,
        longitude=-179.0,
    )
    features = build_features(extreme)
    for name, value in features.items():
        assert value == value, f"{name} = NaN"
        assert abs(value) != float("inf"), f"{name} = inf"


def test_round_amount_detection_is_float_safe() -> None:
    assert build_features(make_transaction(amount=150.0))["is_round_amount"] == 1.0
    assert build_features(make_transaction(amount=149.99))["is_round_amount"] == 0.0
    assert build_features(make_transaction(amount=25.0))["is_round_amount"] == 0.0


def test_features_module_is_standalone() -> None:
    """DoD этапа 05: модуль признаков не должен тянуть web- и ML-зависимости.

    Проверяется в отдельном процессе: внутри pytest pandas и sklearn уже
    загружены другими тестовыми модулями, поэтому проверка `sys.modules`
    в текущем процессе была бы бессмысленной.

    Требование не формальное. Как только в `features/` появится импорт
    FastAPI или sklearn, модуль перестанет быть переиспользуемым: его нельзя
    будет вызвать ни из офлайн-задачи, ни из другого сервиса, а любая правка
    web-слоя начнёт задевать вычисление признаков.
    """
    import os
    import subprocess
    import sys
    from pathlib import Path

    backend_dir = Path(__file__).resolve().parents[1]
    forbidden = ("fastapi", "starlette", "uvicorn", "sklearn", "lightgbm", "shap", "pandas", "numpy")
    script = (
        "import sys;"
        f"sys.path.insert(0, {str(backend_dir)!r});"
        "import app.features.builder, app.features.definitions,"
        " app.features.geo, app.features.merchants;"
        f"forbidden = {forbidden!r};"
        "leaked = sorted({m.split('.')[0] for m in sys.modules} & set(forbidden));"
        "print(','.join(leaked))"
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True, env={**os.environ}, check=True,
    )
    leaked = [name for name in result.stdout.strip().split(",") if name]
    assert not leaked, f"модуль признаков подтянул тяжёлые зависимости: {leaked}"


def test_new_account_threshold_shared_with_dataset() -> None:
    """Порог «нового счёта» обязан быть один на генератор и на признаки."""
    from app.features.builder import NEW_ACCOUNT_THRESHOLD_DAYS as feature_threshold
    from app.ml.dataset import NEW_ACCOUNT_THRESHOLD_DAYS as dataset_threshold

    assert feature_threshold is dataset_threshold
