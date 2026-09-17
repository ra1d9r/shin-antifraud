"""Тесты генератора датасета (ТЗ §5.1–5.2).

Проверяется не «код не падает», а свойства данных, от которых зависит
осмысленность обучения: хронология, согласованность профиля с лентой,
наличие всех сценариев атак и одновременное присутствие сигнала и пересечения
классов.
"""

from __future__ import annotations

import pandas as pd
import pytest

from app.ml.dataset import (
    DEFAULT_END_DATE,
    FraudScenario,
    generate_dataset,
    generate_user_profiles,
    validate_dataset,
)

# Небольшой размер: тесты должны идти быстро, свойства проявляются и здесь.
ROWS = 12_000
USERS = 400
SEED = 2024


@pytest.fixture(scope="module")
def frame() -> pd.DataFrame:
    return generate_dataset(rows=ROWS, users=USERS, fraud_rate=0.02, seed=SEED)


def test_dataset_passes_validation(frame: pd.DataFrame) -> None:
    assert validate_dataset(frame) == []


def test_size_and_users(frame: pd.DataFrame) -> None:
    assert 0.9 * ROWS <= len(frame) <= ROWS
    assert frame["user_id"].nunique() == USERS


def test_fraud_rate_close_to_target(frame: pd.DataFrame) -> None:
    fraud_rate = float(frame["is_fraud"].mean())
    assert 0.012 <= fraud_rate <= 0.03, f"доля фрода {fraud_rate:.3%} далека от целевых 2%"


def test_required_columns_present(frame: pd.DataFrame) -> None:
    """Все поля транзакции из ТЗ §3 должны быть в датасете."""
    required = {
        "transaction_id", "user_id", "amount", "timestamp", "merchant", "country",
        "device_id", "ip_address", "latitude", "longitude", "transaction_frequency",
        "previous_transaction_amount", "previous_transaction_country", "account_age_days",
    }
    assert required.issubset(set(frame.columns))


def test_timeline_is_chronological(frame: pd.DataFrame) -> None:
    """Предыдущая транзакция строго раньше текущей — иначе интервальные признаки лгут."""
    assert (frame["previous_timestamp"] < frame["timestamp"]).all()


def test_previous_fields_match_user_timeline(frame: pd.DataFrame) -> None:
    """previous_* должны совпадать с реальной предыдущей транзакцией клиента."""
    ordered = frame.sort_values(["user_id", "timestamp"])
    expected = ordered.groupby("user_id", observed=True)["country"].shift(1)
    actual = ordered["previous_transaction_country"]
    # Первая транзакция клиента сравнивается с синтетическим стартом — пропускаем.
    comparable = expected.notna()
    assert (expected[comparable] == actual[comparable]).all()


def test_all_fraud_scenarios_present(frame: pd.DataFrame) -> None:
    """Каждый заявленный сценарий атаки должен реально встречаться в данных."""
    present = set(frame.loc[frame["is_fraud"] == 1, "fraud_scenario"].unique())
    expected = {s.value for s in FraudScenario if s is not FraudScenario.NONE}
    missing = expected - present
    assert not missing, f"сценарии отсутствуют в датасете: {missing}"


def test_new_account_abuse_only_on_young_accounts(frame: pd.DataFrame) -> None:
    abuse = frame[frame["fraud_scenario"] == FraudScenario.NEW_ACCOUNT_ABUSE.value]
    if not abuse.empty:
        assert abuse["account_age_days"].max() <= 60


def test_timestamps_within_window(frame: pd.DataFrame) -> None:
    assert frame["timestamp"].max() <= DEFAULT_END_DATE


def test_generation_is_deterministic() -> None:
    first = generate_dataset(rows=3_000, users=100, seed=SEED)
    second = generate_dataset(rows=3_000, users=100, seed=SEED)
    assert first.equals(second)


def test_different_seed_changes_data() -> None:
    first = generate_dataset(rows=3_000, users=100, seed=1)
    second = generate_dataset(rows=3_000, users=100, seed=2)
    assert not first.equals(second)


def test_generation_is_deterministic_across_processes() -> None:
    """Регрессия: воспроизводимость не должна зависеть от хеш-сида процесса.

    Раньше генератор выбирал страну через `rng.choice(tuple(frozenset))`.
    Порядок обхода множества строк зависит от `PYTHONHASHSEED`, который
    Python рандомизирует в каждом процессе, поэтому один и тот же seed
    давал разные датасеты при разных запусках. Проверка внутри одного
    процесса этого не ловит — нужен именно запуск в отдельных процессах
    с разным хеш-сидом.
    """
    import os
    import subprocess
    import sys
    from pathlib import Path

    backend_dir = Path(__file__).resolve().parents[1]
    script = (
        "import sys, hashlib;"
        f"sys.path.insert(0, {str(backend_dir)!r});"
        "from app.ml.dataset import generate_dataset;"
        "frame = generate_dataset(rows=2000, users=60, seed=42);"
        "print(hashlib.md5(frame.to_csv(index=False).encode()).hexdigest())"
    )

    digests = []
    for hash_seed in ("0", "1", "424242"):
        environment = {**os.environ, "PYTHONHASHSEED": hash_seed}
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True, text=True, env=environment, check=True,
        )
        digests.append(result.stdout.strip())

    assert len(set(digests)) == 1, (
        f"датасет зависит от PYTHONHASHSEED — генерация невоспроизводима: {digests}"
    )


def test_fraud_carries_signal(frame: pd.DataFrame) -> None:
    """Сигнал обязан быть: иначе обучать нечему."""
    fraud = frame[frame["is_fraud"] == 1]
    legit = frame[frame["is_fraud"] == 0]

    fraud_abroad = (fraud["country"] != fraud["user_home_country"]).mean()
    legit_abroad = (legit["country"] != legit["user_home_country"]).mean()
    assert fraud_abroad > legit_abroad * 3


def test_classes_overlap(frame: pd.DataFrame) -> None:
    """Пересечение классов обязано быть: иначе задача тривиальна и метрики лгут.

    Проверяем, что заметная часть фрода не имеет грубых аномалий —
    ни чужой страны, ни выдающейся суммы.
    """
    fraud = frame[frame["is_fraud"] == 1]
    subtle = fraud[
        (fraud["country"] == fraud["user_home_country"])
        & (fraud["amount"] < fraud["user_avg_amount"] * 3)
    ]
    assert len(subtle) / len(fraud) > 0.05, "фрод слишком легко отделим — данные нереалистичны"


def test_profiles_are_consistent() -> None:
    import random

    profiles = generate_user_profiles(200, random.Random(SEED))
    assert len(profiles) == 200
    assert all(profile.avg_amount > 0 for profile in profiles)
    assert all(profile.devices for profile in profiles)
    assert len({profile.user_id for profile in profiles}) == 200


def test_rejects_invalid_parameters() -> None:
    with pytest.raises(ValueError):
        generate_dataset(rows=0)
    with pytest.raises(ValueError):
        generate_dataset(fraud_rate=0.9)
