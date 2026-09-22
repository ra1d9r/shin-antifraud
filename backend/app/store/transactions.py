"""Хранилище обработанных транзакций (ТЗ §2.1 `/stats`, §8.2 таблица).

Кольцевой буфер фиксированного размера: прототип работает без базы данных,
а неограниченный список съел бы память за время демонстрации. Размер
задаётся настройкой `MAX_STORED_TRANSACTIONS`.

Статистика считается по тому, что реально прошло через систему, а не
берётся из датасета — это прямое требование ТЗ к эндпоинту `/stats`.
"""

from __future__ import annotations

import threading
from collections import Counter, deque
from dataclasses import dataclass
from datetime import datetime

from app.schemas.enums import Decision, RiskLevel


@dataclass(frozen=True, slots=True)
class TransactionRecord:
    """Обработанная транзакция — то, что видит Dashboard."""

    transaction_id: str
    user_id: str
    timestamp: datetime
    amount: float
    country: str
    merchant: str
    device_id: str
    risk_score: int
    model_score: int
    decision: Decision
    risk_level: RiskLevel
    triggered_rules: tuple[str, ...]
    top_reason: str | None
    # Подсеть /24, а не полный адрес: графу связей нужна только она,
    # а хранить меньше персональных данных — лучше по умолчанию.
    ip_subnet: str | None = None


class TransactionStore:
    """Последние обработанные транзакции и статистика по ним."""

    def __init__(self, capacity: int = 5_000) -> None:
        if capacity <= 0:
            raise ValueError("capacity должен быть положительным")
        self._records: deque[TransactionRecord] = deque(maxlen=capacity)
        self._lock = threading.Lock()
        # Счётчик за всё время работы: он не обнуляется при вытеснении
        # старых записей из буфера, поэтому /health показывает честное
        # число обработанных транзакций.
        self._processed_total = 0

    @property
    def capacity(self) -> int:
        return self._records.maxlen or 0

    @property
    def processed_total(self) -> int:
        with self._lock:
            return self._processed_total

    def add(self, record: TransactionRecord) -> None:
        with self._lock:
            self._records.append(record)
            self._processed_total += 1

    def all(self) -> list[TransactionRecord]:
        with self._lock:
            return list(self._records)

    def size(self) -> int:
        with self._lock:
            return len(self._records)

    def get(self, transaction_id: str) -> TransactionRecord | None:
        """Найти операцию по идентификатору — нужно разметке аналитика.

        Перебор по буферу, а не индекс: записей не больше
        `MAX_STORED_TRANSACTIONS`, а поиск случается раз на ручной разбор.
        Индекс пришлось бы чистить при вытеснении из deque, и это был бы
        второй источник правды о том, что в буфере лежит.

        Идём с конца: идентификатор задаёт клиент, повторы возможны, и
        размечать логично последнюю операцию с таким номером.
        """
        with self._lock:
            for record in reversed(self._records):
                if record.transaction_id == transaction_id:
                    return record
        return None

    def clear(self) -> None:
        with self._lock:
            self._records.clear()
            self._processed_total = 0

    # ------------------------------------------------------------ выборка

    def query(
        self,
        *,
        decision: Decision | None = None,
        flagged: bool | None = None,
        risk_level: RiskLevel | None = None,
        country: str | None = None,
        min_risk_score: int | None = None,
        max_risk_score: int | None = None,
        user_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[int, list[TransactionRecord]]:
        """Отфильтрованный срез истории (ТЗ §8.2).

        Возвращает общее число подошедших записей и запрошенную страницу.
        Порядок — от новых к старым: в таблице сверху должно быть свежее.

        `flagged=True` — всё, что система не пропустила: и CHALLENGE,
        и BLOCK. Отдельным флагом, а не двумя запросами, потому что
        аналитику нужны обе категории разом: его вопрос — «с чем система
        что-то сделала», а не «что именно она сделала».
        """
        records = self.all()
        records.reverse()

        def matches(record: TransactionRecord) -> bool:
            if decision is not None and record.decision is not decision:
                return False
            if flagged is not None:
                held = record.decision is not Decision.APPROVE
                if held is not flagged:
                    return False
            if risk_level is not None and record.risk_level is not risk_level:
                return False
            if country is not None and record.country != country.upper():
                return False
            if user_id is not None and record.user_id != user_id:
                return False
            if min_risk_score is not None and record.risk_score < min_risk_score:
                return False

            # в `return not (...)`. Тогда один фильтр из пяти выглядел бы иначе,
            # чем остальные, и цепочку стало бы труднее читать и дополнять.
            if max_risk_score is not None and record.risk_score > max_risk_score:  # noqa: SIM103
                return False
            return True

        filtered = [record for record in records if matches(record)]
        return len(filtered), filtered[offset : offset + limit]

    # --------------------------------------------------------- статистика

    def statistics(self) -> dict:
        """Сводка по обработанным транзакциям (ТЗ §8.1)."""
        records = self.all()
        total = len(records)

        if total == 0:
            return {
                "total_transactions": 0,
                "suspicious_transactions": 0,
                "blocked_transactions": 0,
                "approved_transactions": 0,
                "average_risk_score": 0.0,
                "fraud_rate": 0.0,
                "decisions": {"approve": 0, "challenge": 0, "block": 0},
                "risk_levels": {},
                "total_amount": 0.0,
                "blocked_amount": 0.0,
                "top_countries": {},
                "triggered_rules": {},
            }

        decisions = Counter(record.decision for record in records)
        levels = Counter(record.risk_level.value for record in records)
        countries = Counter(record.country for record in records)
        rules: Counter = Counter()
        for record in records:
            rules.update(record.triggered_rules)

        approved = decisions[Decision.APPROVE]
        challenged = decisions[Decision.CHALLENGE]
        blocked = decisions[Decision.BLOCK]

        return {
            "total_transactions": total,
            "suspicious_transactions": challenged,
            "blocked_transactions": blocked,
            "approved_transactions": approved,
            "average_risk_score": round(
                sum(record.risk_score for record in records) / total, 2
            ),
            # Доля рискованных по мнению системы — оценка, а не измеренная
            # истина: здесь она судит сама себя. Подтверждённое считает
            # FeedbackStore по разметке аналитика.
            "fraud_rate": round((challenged + blocked) / total, 4),
            "decisions": {"approve": approved, "challenge": challenged, "block": blocked},
            "risk_levels": dict(levels.most_common()),
            "total_amount": round(sum(record.amount for record in records), 2),
            "blocked_amount": round(
                sum(record.amount for record in records if record.decision is Decision.BLOCK), 2
            ),
            "top_countries": dict(countries.most_common(10)),
            "triggered_rules": dict(rules.most_common()),
        }
