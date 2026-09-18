"""Диагностика окружения Shin.

Запуск:
    python backend/scripts/check_setup.py

Проверяет, что установлено всё необходимое, конфигурация читается,
пакеты приложения импортируются и артефакты ML на месте.
Используется как быстрый self-check перед демонстрацией.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

# Делаем пакет `app` импортируемым при запуске скрипта напрямую.
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.console import enable_utf8_output  # noqa: E402 — только после правки sys.path

enable_utf8_output()

OK = "[ OK ]"
FAIL = "[FAIL]"
WARN = "[WARN]"

REQUIRED_PACKAGES = [
    "fastapi", "uvicorn", "pydantic", "pydantic_settings",
    "numpy", "pandas", "sklearn", "joblib",
]
OPTIONAL_PACKAGES = ["lightgbm", "shap"]
APP_PACKAGES = [
    "app.config.settings",
    "app.core.logging",
    "app.core.exceptions",
    "app.schemas.enums",
]


def _check_python() -> bool:
    version = sys.version_info
    ok = version >= (3, 11)
    mark = OK if ok else FAIL
    print(f"{mark} Python {version.major}.{version.minor}.{version.micro} (нужен >= 3.11)")
    return ok


def _check_packages(names: list[str], *, required: bool) -> bool:
    all_ok = True
    for name in names:
        try:
            module = importlib.import_module(name)
            version = getattr(module, "__version__", "?")
            print(f"{OK} {name:<20} {version}")
        except ImportError:
            if required:
                print(f"{FAIL} {name:<20} не установлен")
                all_ok = False
            else:
                print(f"{WARN} {name:<20} не установлен (есть fallback, это не ошибка)")
    return all_ok


def _check_app_imports() -> bool:
    all_ok = True
    for name in APP_PACKAGES:
        try:
            importlib.import_module(name)
            print(f"{OK} import {name}")
        except Exception as exc:  # noqa: BLE001 — диагностике важна любая причина
            print(f"{FAIL} import {name}: {exc}")
            all_ok = False
    return all_ok


def _check_settings() -> bool:
    try:
        from app.config.settings import PROJECT_ROOT, get_settings

        settings = get_settings()
    except Exception as exc:  # noqa: BLE001
        print(f"{FAIL} конфигурация не читается: {exc}")
        return False

    print(f"{OK} конфигурация загружена")
    print(f"       project root : {PROJECT_ROOT}")
    print(f"       app          : {settings.app_name} v{settings.app_version} ({settings.environment})")
    print(f"       пороги риска : APPROVE <= {settings.risk_approve_max} "
          f"< CHALLENGE <= {settings.risk_challenge_max} < BLOCK")
    print(f"       датасет      : {settings.dataset_rows} строк, "
          f"{settings.dataset_users} клиентов, fraud rate {settings.dataset_fraud_rate:.1%}")
    print(f"       CORS origins : {settings.cors_origins_list}")
    return True


def _check_artifacts() -> bool:
    from app.config.settings import get_settings

    settings = get_settings()
    checks = [
        ("датасет", settings.dataset_file, "python backend/scripts/generate_dataset.py"),
        ("модель", settings.model_file, "python backend/scripts/train_model.py"),
    ]
    for label, path, how_to_fix in checks:
        if path.exists():
            size_mb = path.stat().st_size / 1024 / 1024
            print(f"{OK} {label}: {path.name} ({size_mb:.1f} MB)")
        else:
            print(f"{WARN} {label} отсутствует -> создайте командой: {how_to_fix}")
    return True


def main() -> int:
    print("=" * 72)
    print("  Shin Anti-Fraud System — проверка окружения")
    print("=" * 72)

    results: list[bool] = []

    print("\n-- Интерпретатор --")
    results.append(_check_python())

    print("\n-- Обязательные пакеты --")
    results.append(_check_packages(REQUIRED_PACKAGES, required=True))

    print("\n-- Опциональные пакеты --")
    _check_packages(OPTIONAL_PACKAGES, required=False)

    print("\n-- Пакеты приложения --")
    results.append(_check_app_imports())

    print("\n-- Конфигурация --")
    results.append(_check_settings())

    print("\n-- ML-артефакты --")
    try:
        _check_artifacts()
    except Exception as exc:  # noqa: BLE001
        print(f"{WARN} не удалось проверить артефакты: {exc}")

    print("\n" + "=" * 72)
    if all(results):
        print("  РЕЗУЛЬТАТ: окружение готово")
        print("=" * 72)
        return 0

    print("  РЕЗУЛЬТАТ: есть проблемы — см. строки [FAIL] выше")
    print("=" * 72)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
