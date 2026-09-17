"""Настройка логирования.

Один вызов `configure_logging()` при старте приложения и скриптов —
дальше везде используется `get_logger(__name__)`.
"""

from __future__ import annotations

import logging
import sys

_LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)-28s | %(message)s"
_DATE_FORMAT = "%H:%M:%S"
_configured = False


def configure_logging(level: str = "INFO") -> None:
    """Подключить единый форматтер к корневому логгеру (идемпотентно)."""
    global _configured
    if _configured:
        # Обработчики уже стоят, но уровень мог измениться (скрипт и API
        # используют разные настройки) — применяем его и выходим.
        logging.getLogger().setLevel(level.upper())
        return

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(logging.Formatter(fmt=_LOG_FORMAT, datefmt=_DATE_FORMAT))

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())

    # uvicorn дублирует записи своими хендлерами — отключаем дубли
    for noisy in ("uvicorn.access", "uvicorn.error"):
        logging.getLogger(noisy).propagate = False

    _configured = True


def get_logger(name: str) -> logging.Logger:
    """Логгер модуля."""
    return logging.getLogger(name)
