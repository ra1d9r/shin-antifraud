"""Тесты разметки аналитика.

Разметка — единственное в системе, что нельзя пересчитать заново: модель
переобучается, датасет генерируется, а метку ставил человек. Поэтому
проверяется не только «сохранилось и прочиталось», но и то, что метка
переживает порчу файла, недоступный диск и вытеснение транзакции
из буфера.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.schemas.enums import Decision, RiskLevel, Verdict
from app.store.feedback import FeedbackRecord, FeedbackStore, derive_actual_fraud
from app.store.transactions import TransactionRecord, TransactionStore

BASE = datetime(2026, 9, 20, 10, 0, 0)


def label(
    transaction_id: str = "txn_1",
    *,
    decision: Decision = Decision.BLOCK,
    verdict: Verdict = Verdict.CORRECT,
    amount: float = 100.0,
    rules: tuple[str, ...] = (),
    minutes: int = 0,
) -> FeedbackRecord:
    """Метка с выведенной, а не заданной вручную истиной.

    Считать `actual_fraud` в тесте самому значило бы проверять код
    его же формулой; здесь сознательно вызывается та же функция, что
    и в роуте, а корректность самой формулы проверяется отдельно.
    """
    return FeedbackRecord(
        transaction_id=transaction_id,
        user_id="user_1",
        verdict=verdict,
        actual_fraud=derive_actual_fraud(decision, verdict),
        decision=decision,
        risk_score=85,
        model_score=80,
        amount=amount,
        triggered_rules=rules,
        labeled_at=BASE + timedelta(minutes=minutes),
        analyst="ops",
        comment=None,
    )


# ----------------------------------------------------- вывод настоящей метки


@pytest.mark.parametrize(
    ("decision", "verdict", "expected"),
    [
        (Decision.BLOCK, Verdict.CORRECT, True),
        (Decision.BLOCK, Verdict.INCORRECT, False),
        (Decision.CHALLENGE, Verdict.CORRECT, True),
        (Decision.CHALLENGE, Verdict.INCORRECT, False),
        (Decision.APPROVE, Verdict.CORRECT, False),
        (Decision.APPROVE, Verdict.INCORRECT, True),
    ],
)
def test_actual_fraud_is_derived_from_decision(decision, verdict, expected) -> None:
    """«Система была права» значит разное при разных решениях.

    CHALLENGE идёт вместе с BLOCK: проверка — это тоже утверждение
    «здесь что-то не так», и подтверждение такого вердикта означает фрод.
    """
    assert derive_actual_fraud(decision, verdict) is expected


# ----------------------------------------------------------------- хранение


def test_relabeling_replaces_previous_verdict() -> None:
    """Аналитик ошибся и передумал — в разметке должна остаться одна метка."""
    store = FeedbackStore()
    store.add(label("txn_1", verdict=Verdict.CORRECT))
    store.add(label("txn_1", verdict=Verdict.INCORRECT, minutes=5))

    assert store.size() == 1
    assert store.get("txn_1").verdict is Verdict.INCORRECT


def test_labels_are_listed_from_fresh_to_old() -> None:
    store = FeedbackStore()
    store.add(label("txn_old", minutes=0))
    store.add(label("txn_new", minutes=10))

    assert [record.transaction_id for record in store.all()] == ["txn_new", "txn_old"]


# ------------------------------------------------------------ архив на диске


def test_labels_survive_restart(tmp_path: Path) -> None:
    """Главное свойство: перезапуск не стоит аналитику его работы."""
    archive = tmp_path / "nested" / "labels.jsonl"
    first = FeedbackStore(path=archive)
    first.add(label("txn_1", decision=Decision.BLOCK, verdict=Verdict.INCORRECT, amount=250.0))
    first.add(label("txn_2", decision=Decision.APPROVE, verdict=Verdict.INCORRECT, minutes=1))

    second = FeedbackStore(path=archive)
    assert second.load() == 2

    restored = second.get("txn_1")
    assert restored.verdict is Verdict.INCORRECT
    assert restored.actual_fraud is False
    assert restored.decision is Decision.BLOCK
    assert restored.amount == 250.0
    assert restored.labeled_at == BASE


def test_broken_line_does_not_cost_the_whole_archive(tmp_path: Path) -> None:
    """Обрыв записи на середине не повод потерять сотню целых меток."""
    archive = tmp_path / "labels.jsonl"
    good = json.dumps(label("txn_good").to_json(), ensure_ascii=False)
    archive.write_text(
        good + "\n" + '{"transaction_id": "txn_torn", "verdi' + "\n" + "\n",
        encoding="utf-8",
    )

    store = FeedbackStore(path=archive)
    assert store.load() == 1
    assert store.get("txn_good") is not None
    assert store.summary().skipped_lines == 1


def test_last_line_about_a_transaction_wins(tmp_path: Path) -> None:
    """Файл дописывается, поэтому переразметка лежит в нём целиком."""
    archive = tmp_path / "labels.jsonl"
    store = FeedbackStore(path=archive)
    store.add(label("txn_1", verdict=Verdict.CORRECT))
    store.add(label("txn_1", verdict=Verdict.INCORRECT, minutes=5))

    assert len(archive.read_text(encoding="utf-8").strip().splitlines()) == 2

    reloaded = FeedbackStore(path=archive)
    reloaded.load()
    assert reloaded.size() == 1
    assert reloaded.get("txn_1").verdict is Verdict.INCORRECT


def test_missing_archive_is_not_an_error(tmp_path: Path) -> None:
    store = FeedbackStore(path=tmp_path / "never-written.jsonl")
    assert store.load() == 0
    assert store.storage_error is None


def test_unwritable_disk_does_not_lose_the_label(tmp_path: Path) -> None:
    """На эфемерном хостинге диск может быть недоступен.

    Отдать аналитику ошибку на его работу из-за этого нельзя: метка уже
    в памяти и уже полезна. Но и промолчать нельзя — иначе пропажа архива
    обнаружится только после перезапуска.
    """
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("файл там, где ожидался каталог", encoding="utf-8")

    store = FeedbackStore(path=blocker / "labels.jsonl")
    store.add(label("txn_1"))

    assert store.size() == 1
    assert store.storage_error is not None
    assert "перезапуске" in store.storage_error
    assert store.summary().storage_error == store.storage_error


def test_clear_keeps_the_archive(tmp_path: Path) -> None:
    """Память чистится, файл — нет: он архив, а не кэш."""
    archive = tmp_path / "labels.jsonl"
    store = FeedbackStore(path=archive)
    store.add(label("txn_1"))
    store.clear()

    assert store.size() == 0
    assert archive.exists()


# -------------------------------------------------------------------- сводка


def test_empty_summary_says_unknown_not_zero() -> None:
    """«Точность 0 %» и «точность ещё не измерена» — разные утверждения."""
    summary = FeedbackStore().summary()

    assert summary.labeled_total == 0
    assert summary.correct_share is None
    assert summary.precision is None
    assert summary.recall is None
    assert summary.by_decision == []


def test_summary_measures_quality_on_confirmed_labels() -> None:
    store = FeedbackStore()
    store.add(label("t1", decision=Decision.BLOCK, verdict=Verdict.CORRECT))
    store.add(label("t2", decision=Decision.BLOCK, verdict=Verdict.INCORRECT, minutes=1))
    store.add(label("t3", decision=Decision.CHALLENGE, verdict=Verdict.CORRECT, minutes=2))
    store.add(label("t4", decision=Decision.APPROVE, verdict=Verdict.CORRECT, minutes=3))
    store.add(
        label("t5", decision=Decision.APPROVE, verdict=Verdict.INCORRECT, amount=900.0, minutes=4)
    )

    summary = store.summary()

    assert summary.labeled_total == 5
    assert (summary.correct, summary.incorrect) == (3, 2)
    assert summary.correct_share == 0.6
    assert (summary.fraud_confirmed, summary.legit_confirmed) == (3, 2)

    # Положительный ответ системы — это CHALLENGE и BLOCK.
    assert (summary.true_positive, summary.false_positive) == (2, 1)
    assert (summary.false_negative, summary.true_negative) == (1, 1)
    assert summary.precision == round(2 / 3, 4)
    assert summary.recall == round(2 / 3, 4)

    # Пропущенный фрод — единственное, чему здесь можно назвать цену.
    assert summary.fraud_amount_missed == 900.0


def test_summary_breaks_down_by_decision() -> None:
    store = FeedbackStore()
    store.add(label("t1", decision=Decision.BLOCK, verdict=Verdict.CORRECT))
    store.add(label("t2", decision=Decision.BLOCK, verdict=Verdict.INCORRECT, minutes=1))
    store.add(label("t3", decision=Decision.APPROVE, verdict=Verdict.CORRECT, minutes=2))

    rows = {row.decision: row for row in store.summary().by_decision}

    assert rows[Decision.BLOCK].labeled == 2
    assert (rows[Decision.BLOCK].fraud, rows[Decision.BLOCK].legit) == (1, 1)
    assert (rows[Decision.APPROVE].fraud, rows[Decision.APPROVE].legit) == (0, 1)
    # Решения без единой метки в сводке не появляются: строка из нулей
    # выглядела бы как измерение, которого не было.
    assert Decision.CHALLENGE not in rows


def test_summary_shows_which_policies_only_add_friction() -> None:
    """Дашборд считает предельный вклад политик по датасету.

    Здесь то же самое, но по подтверждённым операциям: политика, которая
    срабатывает только на добросовестных клиентах, видна сразу.
    """
    store = FeedbackStore()
    store.add(
        label(
            "t1",
            decision=Decision.BLOCK,
            verdict=Verdict.INCORRECT,
            rules=("new_device", "unusual_country"),
        )
    )
    store.add(
        label(
            "t2",
            decision=Decision.BLOCK,
            verdict=Verdict.INCORRECT,
            rules=("new_device",),
            minutes=1,
        )
    )
    store.add(
        label(
            "t3",
            decision=Decision.BLOCK,
            verdict=Verdict.CORRECT,
            rules=("unusual_country",),
            minutes=2,
        )
    )

    rules = {row.key: row for row in store.summary().rules}

    assert (rules["new_device"].labeled, rules["new_device"].fraud) == (2, 0)
    assert (rules["unusual_country"].fraud, rules["unusual_country"].legit) == (1, 1)


# ------------------------------------------ поиск размечаемой транзакции


def test_transaction_lookup_returns_the_latest_duplicate() -> None:
    """Идентификатор задаёт клиент, повторы возможны — размечаем свежую."""
    store = TransactionStore(capacity=10)
    for score in (10, 90):
        store.add(
            TransactionRecord(
                transaction_id="txn_same",
                user_id="u",
                timestamp=BASE,
                amount=50.0,
                country="KZ",
                merchant="Magnum",
                device_id="dev",
                risk_score=score,
                model_score=score,
                decision=Decision.APPROVE if score < 50 else Decision.BLOCK,
                risk_level=RiskLevel.LOW if score < 50 else RiskLevel.CRITICAL,
                triggered_rules=(),
                top_reason=None,
            )
        )

    assert store.get("txn_same").risk_score == 90
    assert store.get("txn_never-was") is None
