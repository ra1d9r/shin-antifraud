"""Профили клиентов в памяти (решение D-4).

Признаки «отклонение от обычного поведения» требуют знать, каким это
обычное поведение было. В проде такие данные приходят из профильного
хранилища; для прототипа достаточно накапливать их в памяти процесса.

Профиль обновляется **после** того, как решение по транзакции принято:
иначе текущая операция сама себя объявила бы привычной, и признак
«новое устройство» никогда бы не срабатывал.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta

# Сколько устройств помним на клиента. Без ограничения список рос бы
# бесконечно, а «известным» становилось бы любое устройство.
MAX_KNOWN_DEVICES = 20

# Окно, в котором считаем частоту операций.
FREQUENCY_WINDOW_HOURS = 24


@dataclass(slots=True)
class UserProfile:
    """Накопленное знание о клиенте."""

    user_id: str
    known_devices: list[str] = field(default_factory=list)
    home_country: str | None = None
    transaction_count: int = 0
    amount_sum: float = 0.0
    amount_square_sum: float = 0.0
    country_counts: dict[str, int] = field(default_factory=dict)
    recent_timestamps: list[datetime] = field(default_factory=list)

    previous_amount: float | None = None
    previous_country: str | None = None
    previous_ip_address: str | None = None
    previous_timestamp: datetime | None = None
    previous_latitude: float | None = None
    previous_longitude: float | None = None

    @property
    def average_amount(self) -> float | None:
        if self.transaction_count == 0:
            return None
        return self.amount_sum / self.transaction_count

    @property
    def amount_std(self) -> float | None:
        """Стандартное отклонение суммы по накопленным моментам."""
        if self.transaction_count < 2:
            return None
        mean = self.amount_sum / self.transaction_count
        variance = self.amount_square_sum / self.transaction_count - mean * mean
        return max(variance, 0.0) ** 0.5

    @property
    def dominant_country(self) -> str | None:
        """Страна, в которой клиент платит чаще всего."""
        if not self.country_counts:
            return self.home_country
        return max(self.country_counts.items(), key=lambda item: item[1])[0]

    def count_recent(self, now: datetime, hours: int) -> int:
        threshold = now - timedelta(hours=hours)
        return sum(1 for moment in self.recent_timestamps if moment >= threshold)

    @property
    def typical_daily_frequency(self) -> float | None:
        """Обычное число операций в сутки.

        Считается по операциям **внутри окна** и размаху этого же окна.
        Смешивать нельзя: `transaction_count` растёт за всё время жизни
        профиля, а `recent_timestamps` обрезан сутками. Деление одного
        на другое давало завышение в десятки раз — у клиента с месячной
        историей выходило 114 операций в сутки вместо 3.4, и признак
        `frequency_ratio` переставал что-либо значить.

        Пока в окне меньше двух операций или размах меньше часа, величина
        не определена: лучше вернуть None и дать feature builder применить
        нейтральное значение, чем выдумать число.
        """
        if len(self.recent_timestamps) < 2:
            return None

        span_hours = (
            self.recent_timestamps[-1] - self.recent_timestamps[0]
        ).total_seconds() / 3600.0
        if span_hours < 1.0:
            return None
        return len(self.recent_timestamps) / (span_hours / 24.0)


class UserProfileStore:
    """Потокобезопасное хранилище профилей.

    Uvicorn обслуживает запросы в нескольких потоках, поэтому изменения
    состояния защищены блокировкой: без неё два одновременных запроса
    одного клиента могли бы затереть обновления друг друга.
    """

    def __init__(self) -> None:
        self._profiles: dict[str, UserProfile] = {}
        self._lock = threading.Lock()

    def get(self, user_id: str) -> UserProfile | None:
        with self._lock:
            profile = self._profiles.get(user_id)
            return profile

    def record(
        self,
        user_id: str,
        *,
        amount: float,
        country: str,
        device_id: str,
        ip_address: str,
        timestamp: datetime,
        latitude: float,
        longitude: float,
    ) -> None:
        """Учесть обработанную транзакцию в профиле клиента."""
        with self._lock:
            profile = self._profiles.get(user_id)
            if profile is None:
                profile = UserProfile(user_id=user_id)
                self._profiles[user_id] = profile

            if device_id not in profile.known_devices:
                profile.known_devices.append(device_id)
                if len(profile.known_devices) > MAX_KNOWN_DEVICES:
                    del profile.known_devices[0]

            profile.transaction_count += 1
            profile.amount_sum += amount
            profile.amount_square_sum += amount * amount
            profile.country_counts[country] = profile.country_counts.get(country, 0) + 1

            if profile.home_country is None:
                profile.home_country = country

            profile.recent_timestamps.append(timestamp)
            profile.recent_timestamps.sort()
            # Окно отсчитывается от САМОЙ ПОЗДНЕЙ известной операции, а не от
            # входящей. Транзакции приходят не строго по порядку (симулятор
            # позволяет задать любое время), и отсчёт от входящей метки
            # означал бы, что одна операция «из прошлого» отменяет обрезку
            # и окно растёт без границ.
            cutoff = profile.recent_timestamps[-1] - timedelta(hours=FREQUENCY_WINDOW_HOURS)
            profile.recent_timestamps = [
                moment for moment in profile.recent_timestamps if moment >= cutoff
            ]

            profile.previous_amount = amount
            profile.previous_country = country
            profile.previous_ip_address = ip_address
            profile.previous_timestamp = timestamp
            profile.previous_latitude = latitude
            profile.previous_longitude = longitude

    def size(self) -> int:
        with self._lock:
            return len(self._profiles)

    def clear(self) -> None:
        with self._lock:
            self._profiles.clear()
