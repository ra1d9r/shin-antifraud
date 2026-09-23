"""Разметка аналитика — единственный источник настоящих меток в проде.

Система знает, что она **решила**, но не знает, была ли права. Поэтому
`GET /stats` честно называет свою `fraud_rate` оценкой, а не измеренной
истиной: подтверждать вердикты в работающей системе некому. Настоящая
разметка есть только в обучающем датасете, и она устаревает вместе с ним.

Здесь этот разрыв закрывается. Аналитик, разобравший операцию, отмечает
вердикт верным или ошибочным — и из отметки выводится настоящая метка:
была ли транзакция мошеннической.

Накопленное — не журнал кликов, а датасет. Из этого следуют два решения,
которые иначе выглядели бы избыточными.

**Запись хранит слепок решения, а не ссылку на транзакцию.** Буфер
обработанных транзакций ограничен (`MAX_STORED_TRANSACTIONS`), и к моменту
дообучения самой транзакции в памяти уже не будет. Метка без контекста —
мусор, поэтому Risk Score, решение и сработавшие политики копируются
в момент разметки.

**Метки переживают перезапуск.** Разметка — ручная работа человека,
терять её при рестарте нельзя. Файл дописывается построчно (JSON Lines):
формат переживает обрыв на середине строки, читается глазами и годится
на вход скрипту дообучения без конвертации.
"""

from __future__ import annotations

import json
import threading
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.core.logging import get_logger
from app.schemas.enums import Decision, Verdict

logger = get_logger("shin.store.feedback")

# Решения, которыми система объявляет операцию подозрительной.
# CHALLENGE попадает сюда вместе с BLOCK: проверка — это тоже
# «система считает, что здесь что-то не так».
FLAGGED_DECISIONS = frozenset({Decision.CHALLENGE, Decision.BLOCK})


def derive_actual_fraud(decision: Decision, verdict: Verdict) -> bool:
    """Вывести настоящую метку из отметки аналитика.

    Аналитик отвечает на вопрос «система была права?», а не «это фрод?».
    Так короче для человека: он только что прочитал вердикт, ему остаётся
    согласиться или нет. Метка выводится однозначно, потому что известно,
    что именно система утверждала: CHALLENGE и BLOCK означают «подозрительно»,
    APPROVE — «чисто».
    """
    flagged = decision in FLAGGED_DECISIONS
    return flagged if verdict is Verdict.CORRECT else not flagged


@dataclass(frozen=True, slots=True)
class FeedbackRecord:
    """Одна метка: что решила система и что оказалось на самом деле."""

    transaction_id: str
    user_id: str
    verdict: Verdict
    actual_fraud: bool
    decision: Decision
    risk_score: int
    model_score: int
    amount: float
    triggered_rules: tuple[str, ...]
    labeled_at: datetime
    analyst: str | None = None
    comment: str | None = None

    def to_json(self) -> dict:
        return {
            "transaction_id": self.transaction_id,
            "user_id": self.user_id,
            "verdict": self.verdict.value,
            "actual_fraud": self.actual_fraud,
            "decision": self.decision.value,
            "risk_score": self.risk_score,
            "model_score": self.model_score,
            "amount": self.amount,
            "triggered_rules": list(self.triggered_rules),
            "labeled_at": self.labeled_at.isoformat(),
            "analyst": self.analyst,
            "comment": self.comment,
        }

    @classmethod
    def from_json(cls, payload: dict) -> FeedbackRecord:
        """Разобрать строку файла. Бросает при любой порче — так и задумано.

        Вызывающий пропускает битую строку и считает остальные: одна
        недописанная запись не повод потерять сотню целых.
        """
        return cls(
            transaction_id=str(payload["transaction_id"]),
            user_id=str(payload["user_id"]),
            verdict=Verdict(payload["verdict"]),
            actual_fraud=bool(payload["actual_fraud"]),
            decision=Decision(payload["decision"]),
            risk_score=int(payload["risk_score"]),
            model_score=int(payload["model_score"]),
            amount=float(payload["amount"]),
            triggered_rules=tuple(str(key) for key in payload.get("triggered_rules", ())),
            labeled_at=datetime.fromisoformat(payload["labeled_at"]),
            analyst=payload.get("analyst"),
            comment=payload.get("comment"),
        )


@dataclass(frozen=True, slots=True)
class RuleFeedback:
    """Как политика выглядит на подтверждённых данных."""

    key: str
    labeled: int
    fraud: int
    legit: int


@dataclass(frozen=True, slots=True)
class DecisionFeedback:
    """Сколько меток собрано на каждое решение и что они показали."""

    decision: Decision
    labeled: int
    fraud: int
    legit: int


@dataclass(frozen=True, slots=True)
class FeedbackSummary:
    """Что накопленная разметка говорит о качестве системы.

    Матрица ошибок считается относительно того, объявила ли система
    операцию подозрительной: CHALLENGE и BLOCK — положительный ответ,
    APPROVE — отрицательный.
    """

    labeled_total: int
    correct: int
    incorrect: int
    correct_share: float | None
    fraud_confirmed: int
    legit_confirmed: int
    true_positive: int
    false_positive: int
    true_negative: int
    false_negative: int
    precision: float | None
    recall: float | None
    fraud_amount_missed: float
    by_decision: list[DecisionFeedback]
    rules: list[RuleFeedback]
    storage_path: str | None
    storage_error: str | None
    skipped_lines: int


def _ratio(numerator: int, denominator: int) -> float | None:
    """Доля или `None`, когда делить не на что.

    Ноль вместо `None` был бы враньём: «точность 0 %» и «точность ещё
    не измерена» — разные утверждения, и на дашборде они должны
    выглядеть по-разному.
    """
    if denominator == 0:
        return None
    return round(numerator / denominator, 4)


class FeedbackStore:
    """Метки аналитика: в памяти для чтения, на диске — чтобы не пропали."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path
        self._records: dict[str, FeedbackRecord] = {}
        self._lock = threading.Lock()
        self._storage_error: str | None = None
        self._skipped_lines = 0

    # ------------------------------------------------------------- чтение

    @property
    def path(self) -> Path | None:
        return self._path

    @property
    def storage_error(self) -> str | None:
        """Почему метки не пишутся на диск. `None` — пишутся."""
        return self._storage_error

    def size(self) -> int:
        with self._lock:
            return len(self._records)

    def get(self, transaction_id: str) -> FeedbackRecord | None:
        with self._lock:
            return self._records.get(transaction_id)

    def all(self) -> list[FeedbackRecord]:
        """Все метки, от свежих к старым."""
        with self._lock:
            records = list(self._records.values())
        records.sort(key=lambda record: record.labeled_at, reverse=True)
        return records

    def clear(self) -> None:
        """Очистить память. Файл не трогается: он — архив, а не кэш."""
        with self._lock:
            self._records.clear()

    # -------------------------------------------------------------- запись

    def add(self, record: FeedbackRecord) -> FeedbackRecord:
        """Сохранить метку. Повторная разметка той же операции заменяет прежнюю.

        Запись в файл идёт под тем же замком, что и правка памяти. Разметку
        ставит человек, и упереться в скорость записи здесь невозможно,
        зато порядок строк в файле гарантированно совпадает с порядком
        решений — иначе разбор архива пришлось бы делать по меткам времени.
        """
        with self._lock:
            self._records[record.transaction_id] = record
            self._append_to_file(record)
        return record

    def _append_to_file(self, record: FeedbackRecord) -> None:
        """Дописать строку. Неудача не срывает разметку.

        На бесплатном хостинге файловая система может оказаться недоступной
        для записи, а сам контейнер — эфемерным. Отдавать аналитику ошибку
        на его работу из-за этого нельзя: метка уже в памяти и уже полезна.
        Причина запоминается и уходит в сводку, чтобы пропажа архива
        не осталась незамеченной.
        """
        if self._path is None:
            return

        line = json.dumps(record.to_json(), ensure_ascii=False)
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            # Открываем и закрываем на каждую запись намеренно: меток мало,
            # а висящий дескриптор пережил бы падение процесса хуже, чем
            # закрытый файл.
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        except OSError as exc:
            self._storage_error = (
                f"Метки не сохраняются на диск ({exc}). "
                "Накопленная разметка пропадёт при перезапуске."
            )
            logger.error("%s", self._storage_error)

    def load(self) -> int:
        """Прочитать архив меток. Никогда не бросает.

        Возвращает число загруженных меток. Битые строки пропускаются
        и считаются: приложение, которое не поднялось из-за одной
        недописанной строки, хуже приложения с неполной разметкой.
        """
        if self._path is None or not self._path.exists():
            return 0

        loaded: dict[str, FeedbackRecord] = {}
        skipped = 0
        try:
            with self._path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = FeedbackRecord.from_json(json.loads(line))
                    except (ValueError, KeyError, TypeError):
                        skipped += 1
                        continue
                    # Последняя строка про транзакцию выигрывает: файл
                    # дописывается, а не переписывается, поэтому история
                    # переразметки лежит в нём целиком.
                    loaded[record.transaction_id] = record
        except OSError as exc:
            self._storage_error = f"Архив меток не прочитан ({exc})."
            logger.error("%s", self._storage_error)
            return 0

        with self._lock:
            self._records = loaded
            self._skipped_lines = skipped

        if skipped:
            logger.warning("В архиве меток пропущено битых строк: %s", skipped)
        logger.info("Загружено меток аналитика: %s", len(loaded))
        return len(loaded)

    # ----------------------------------------------------------- сводка

    def summary(self) -> FeedbackSummary:
        """Свести разметку в измеренное качество.

        Важная оговорка, которая должна дойти до читателя вместе с числами:
        размеченное — не случайная выборка. Аналитик разбирает то, что
        система пометила, поэтому полнота (recall) здесь смещена вверх:
        пропущенный фрод попадает в разметку только тогда, когда о нём
        сообщил клиент. Точность (precision) смещена куда меньше и потому
        полезнее.
        """
        records = self.all()
        total = len(records)

        correct = sum(1 for record in records if record.verdict is Verdict.CORRECT)
        fraud_confirmed = sum(1 for record in records if record.actual_fraud)

        flagged = [record for record in records if record.decision in FLAGGED_DECISIONS]
        approved = [record for record in records if record.decision not in FLAGGED_DECISIONS]

        true_positive = sum(1 for record in flagged if record.actual_fraud)
        false_positive = len(flagged) - true_positive
        false_negative = sum(1 for record in approved if record.actual_fraud)
        true_negative = len(approved) - false_negative

        decisions: Counter[Decision] = Counter(record.decision for record in records)
        decision_fraud: Counter[Decision] = Counter(
            record.decision for record in records if record.actual_fraud
        )
        by_decision = [
            DecisionFeedback(
                decision=decision,
                labeled=decisions[decision],
                fraud=decision_fraud[decision],
                legit=decisions[decision] - decision_fraud[decision],
            )
            for decision in Decision
            if decisions[decision]
        ]

        rule_labeled: Counter[str] = Counter()
        rule_fraud: Counter[str] = Counter()
        for record in records:
            for key in record.triggered_rules:
                rule_labeled[key] += 1
                if record.actual_fraud:
                    rule_fraud[key] += 1
        rules = [
            RuleFeedback(
                key=key,
                labeled=count,
                fraud=rule_fraud[key],
                legit=count - rule_fraud[key],
            )
            for key, count in rule_labeled.most_common()
        ]

        return FeedbackSummary(
            labeled_total=total,
            correct=correct,
            incorrect=total - correct,
            correct_share=_ratio(correct, total),
            fraud_confirmed=fraud_confirmed,
            legit_confirmed=total - fraud_confirmed,
            true_positive=true_positive,
            false_positive=false_positive,
            true_negative=true_negative,
            false_negative=false_negative,
            precision=_ratio(true_positive, len(flagged)),
            recall=_ratio(true_positive, true_positive + false_negative),
            # Во что обошлись пропуски по тем операциям, где это подтверждено.
            fraud_amount_missed=round(
                sum(record.amount for record in approved if record.actual_fraud), 2
            ),
            by_decision=by_decision,
            rules=rules,
            storage_path=str(self._path) if self._path else None,
            storage_error=self._storage_error,
            skipped_lines=self._skipped_lines,
        )
