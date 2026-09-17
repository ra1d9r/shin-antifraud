"""Корректный вывод кириллицы в консоль.

На Windows стандартная кодовая страница консоли — не UTF-8, из-за чего
русскоязычные сообщения скриптов превращаются в мусор. Функция вызывается
первой строкой в каждом CLI-скрипте проекта.
"""

from __future__ import annotations

import sys


def enable_utf8_output() -> None:
    """Переключить stdout/stderr на UTF-8, если они в другой кодировке."""
    for stream in (sys.stdout, sys.stderr):
        encoding = getattr(stream, "encoding", None)
        if encoding and encoding.lower().replace("-", "") == "utf8":
            continue
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                # Поток не поддерживает смену кодировки — не повод падать.
                pass
