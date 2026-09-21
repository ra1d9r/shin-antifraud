"""Идемпотентность `POST /predict` по `transaction_id`.

## Что ломается без неё

Повтор запроса — обычное дело: клиент не дождался ответа и переспросил,
прокси повторил за него, пользователь нажал кнопку дважды. Сейчас каждый
такой повтор обрабатывается заново, и последствий четыре.

Операция дважды попадает в историю и дважды считается в `/stats`.
Дважды учитывается наблюдением за дрейфом и теневым сравнением.
Профиль клиента обновляется дважды: устройство запоминается, счётчик
частоты сдвигается.

И самое неприятное — **второй ответ может отличаться от первого**.
Именно потому, что профиль уже обновлён первым вызовом: устройство,
которое было новым, новым быть перестало. Клиент переспросил из-за
таймаута и получил другой вердикт по той же операции.

## Что делает этот модуль

Запоминает ответ по `transaction_id`. Повтор с тем же телом получает
тот же ответ, а состояние системы не трогается вовсе.

Повтор с **другим** телом — это не повтор, а вторая операция под чужим
номером, и ответ на неё 409. Вернуть закэшированное было бы хуже
молчаливой ошибки: клиент получил бы решение по чужим данным и не узнал
бы об этом.

## Чего здесь нет

**Срока жизни ключа.** У платёжных систем он есть, но там ключи
хранятся месяцами в базе; здесь хранилище ограничено по размеру,
и вытеснение делает ту же работу. Очень поздний повтор обработается
заново — это задокументированная граница, а не сюрприз.

**Режима «что если».** `persist=false` ничего не меняет и существует
ровно для того, чтобы гонять один и тот же ввод сколько угодно раз.
Кэшировать его значило бы сломать единственный инструмент, ради
которого он сделан.
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections import OrderedDict
from dataclasses import dataclass

from app.core.exceptions import ShinError


class IdempotencyConflictError(ShinError):
    """Тот же `transaction_id`, но другие данные."""

    status_code = 409
    error_code = "idempotency_conflict"


def fingerprint(payload: dict) -> str:
    """Отпечаток тела запроса.

    Сортировка ключей обязательна: порядок полей в JSON произволен,
    и без неё один и тот же запрос давал бы разные отпечатки в
    зависимости от того, как его собрал клиент.
    """
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class StoredResult:
    """Ответ, выданный по этой операции в первый раз."""

    digest: str
    response: object


class IdempotencyStore:
    """Ответы по `transaction_id` с вытеснением самых старых."""

    def __init__(self, capacity: int = 5_000) -> None:
        if capacity <= 0:
            raise ValueError("capacity должен быть положительным")
        self._capacity = capacity
        self._entries: OrderedDict[str, StoredResult] = OrderedDict()
        self._lock = threading.Lock()
        self._replays = 0
        self._conflicts = 0

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def replays(self) -> int:
        """Сколько запросов обслужено повтором вместо обработки."""
        with self._lock:
            return self._replays

    @property
    def conflicts(self) -> int:
        with self._lock:
            return self._conflicts

    def size(self) -> int:
        with self._lock:
            return len(self._entries)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._replays = 0
            self._conflicts = 0

    def lookup(self, transaction_id: str, digest: str) -> object | None:
        """Найти прежний ответ по операции.

        Возвращает `None`, если операция встречается впервые. Бросает
        `IdempotencyConflictError`, если номер тот же, а данные другие.
        """
        with self._lock:
            stored = self._entries.get(transaction_id)
            if stored is None:
                return None

            if stored.digest != digest:
                self._conflicts += 1
                raise IdempotencyConflictError(
                    f"Операция {transaction_id} уже обработана с другими данными. "
                    "Повтор с тем же номером должен содержать то же тело запроса; "
                    "для другой операции задайте другой transaction_id.",
                    details={"transaction_id": transaction_id},
                )

            # Свежие обращения отодвигают запись от края вытеснения:
            # то, что переспрашивают, нужнее того, что забыли.
            self._entries.move_to_end(transaction_id)
            self._replays += 1
            return stored.response

    def has_conflict(self, transaction_id: str, digest: str) -> bool:
        """Занят ли номер операции другими данными.

        Отличается от `lookup` тем, что ничего не меняет: не считает
        повторы, не двигает запись от края вытеснения и не бросает
        исключение. Нужна партии, которая обязана найти все конфликты
        **до** того, как обработает хоть одну операцию, — иначе падение
        на середине оставило бы часть партии записанной, а клиент
        получил бы только ошибку и не знал, что именно прошло.
        """
        with self._lock:
            stored = self._entries.get(transaction_id)
            return stored is not None and stored.digest != digest

    def remember(self, transaction_id: str, digest: str, response: object) -> None:
        with self._lock:
            self._entries[transaction_id] = StoredResult(digest=digest, response=response)
            self._entries.move_to_end(transaction_id)
            while len(self._entries) > self._capacity:
                self._entries.popitem(last=False)
