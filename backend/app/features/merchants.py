"""Справочник мерчантов и категорий.

Лежит на уровне `features`, а не внутри генератора датасета, потому что нужен
обоим потребителям: генерации обучающих данных и инференсу (по названию
мерчанта определяется категория, а по категории — уровень риска).
"""

from __future__ import annotations

# (название мерчанта, категория)
MERCHANTS: tuple[tuple[str, str], ...] = (
    ("Magnum", "grocery"),
    ("Small Market", "grocery"),
    ("Carrefour", "grocery"),
    ("Technodom", "electronics"),
    ("Sulpak", "electronics"),
    ("Apple Store", "electronics"),
    ("Air Astana", "travel"),
    ("Booking.com", "travel"),
    ("Aviata", "travel"),
    ("Wolt", "restaurant"),
    ("Chocofood", "restaurant"),
    ("Starbucks", "restaurant"),
    ("Yandex Go", "transport"),
    ("InDrive", "transport"),
    ("Netflix", "streaming"),
    ("Spotify", "streaming"),
    ("Europharma", "pharmacy"),
    ("LC Waikiki", "fashion"),
    ("Zara", "fashion"),
    ("Steam", "gaming"),
    ("PlayStation Store", "gaming"),
    ("ATM Withdrawal", "atm"),
    ("Binance", "crypto"),
    ("Bybit", "crypto"),
    ("1xBet", "gambling"),
    ("Pin-Up", "gambling"),
    ("Western Union", "money_transfer"),
    ("Swift Transfer", "money_transfer"),
)

MERCHANT_CATEGORY: dict[str, str] = dict(MERCHANTS)

UNKNOWN_CATEGORY = "unknown"

# Категории, через которые чаще всего выводят украденные средства.
HIGH_RISK_CATEGORIES: frozenset[str] = frozenset(
    {"crypto", "gambling", "money_transfer", "atm"}
)

EVERYDAY_MERCHANTS: tuple[str, ...] = tuple(
    name for name, category in MERCHANTS if category not in HIGH_RISK_CATEGORIES
)
CASHOUT_MERCHANTS: tuple[str, ...] = tuple(
    name for name, category in MERCHANTS if category in HIGH_RISK_CATEGORIES
)
# Мерчанты, удобные для «прозвона» украденной карты мелкими суммами.
CARD_TESTING_MERCHANTS: tuple[str, ...] = (
    "Steam", "PlayStation Store", "Netflix", "Spotify", "Booking.com",
)

ALL_MERCHANTS: tuple[str, ...] = tuple(name for name, _ in MERCHANTS)

# Мерчанты мелких повседневных трат: кофе, такси, подписки.
# Нужны, чтобы мелкая сумма сама по себе не означала прозвон карты.
SMALL_TICKET_MERCHANTS: tuple[str, ...] = (
    "Yandex Go", "InDrive", "Starbucks", "Netflix", "Spotify",
    "Small Market", "Wolt", "Chocofood",
)

# Крупные законные покупки.
BIG_TICKET_MERCHANTS: tuple[str, ...] = (
    "Technodom", "Apple Store", "Sulpak", "Air Astana", "Booking.com", "Zara",
)


def merchant_category(merchant: str) -> str:
    """Категория мерчанта. Незнакомое название — не ошибка, а `unknown`."""
    return MERCHANT_CATEGORY.get(merchant, UNKNOWN_CATEGORY)


def is_high_risk_category(category: str) -> bool:
    return category in HIGH_RISK_CATEGORIES
