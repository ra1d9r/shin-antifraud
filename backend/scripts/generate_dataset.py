"""Генерация синтетического датасета транзакций (ТЗ §5.1).

Запуск с параметрами по умолчанию из .env:
    python backend/scripts/generate_dataset.py

Явные параметры:
    python backend/scripts/generate_dataset.py --rows 100000 --users 3000 --seed 42
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import pandas as pd  # noqa: E402

from app.config.settings import get_settings  # noqa: E402
from app.core.console import enable_utf8_output  # noqa: E402
from app.core.logging import configure_logging, get_logger  # noqa: E402
from app.ml.dataset import dataset_summary, generate_dataset, validate_dataset  # noqa: E402

enable_utf8_output()
logger = get_logger("shin.dataset")


def parse_args() -> argparse.Namespace:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Генератор датасета транзакций Shin")
    parser.add_argument("--rows", type=int, default=settings.dataset_rows, help="количество транзакций")
    parser.add_argument("--users", type=int, default=settings.dataset_users, help="количество клиентов")
    parser.add_argument("--fraud-rate", type=float, default=settings.dataset_fraud_rate, help="доля фрода")
    parser.add_argument("--seed", type=int, default=settings.random_seed, help="зерно генератора")
    parser.add_argument("--output", type=str, default=None, help="путь к CSV (по умолчанию из .env)")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    settings = get_settings()
    configure_logging(settings.log_level)

    output_path = Path(args.output).resolve() if args.output else settings.dataset_file
    output_path.parent.mkdir(parents=True, exist_ok=True)

    logger.info(
        "Генерация датасета: rows=%s users=%s fraud_rate=%.3f seed=%s",
        args.rows, args.users, args.fraud_rate, args.seed,
    )

    started = time.perf_counter()
    try:
        frame = generate_dataset(
            rows=args.rows,
            users=args.users,
            fraud_rate=args.fraud_rate,
            seed=args.seed,
        )
    except ValueError as exc:
        logger.error("Некорректные параметры генерации: %s", exc)
        return 1

    elapsed = time.perf_counter() - started

    problems = validate_dataset(frame)
    if problems:
        print()
        print("=" * 72)
        print("  ВАЛИДАЦИЯ НЕ ПРОЙДЕНА — датасет не сохранён")
        print("=" * 72)
        for problem in problems:
            print(f"  - {problem}")
        print("=" * 72)
        return 1

    frame.to_csv(output_path, index=False)

    # Читаем записанный файл обратно: часть дефектов появляется только при
    # сериализации (неоднородный формат времени, потеря типов).
    restored = pd.read_csv(output_path, parse_dates=["timestamp", "previous_timestamp"])
    for column in ("timestamp", "previous_timestamp"):
        if not pd.api.types.is_datetime64_any_dtype(restored[column]):
            print(f"\nОШИБКА: колонка {column} не читается обратно как дата — формат неоднороден")
            return 1

    problems = validate_dataset(restored)
    if problems:
        print("\nОШИБКА: файл записан, но не проходит валидацию после чтения:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    summary = dataset_summary(frame)
    size_mb = output_path.stat().st_size / 1024 / 1024

    print()
    print("=" * 72)
    print("  Датасет сгенерирован")
    print("=" * 72)
    print(f"  файл              : {output_path}")
    print(f"  размер            : {size_mb:.1f} MB")
    print(f"  время генерации   : {elapsed:.1f} с")
    print(f"  транзакций        : {summary['rows']:,}".replace(",", " "))
    print(f"  клиентов          : {summary['users']:,}".replace(",", " "))
    print(f"  период            : {summary['date_from']} — {summary['date_to']}")
    print(f"  стран / мерчантов : {summary['countries']} / {summary['merchants']}")
    print()
    print(f"  фрод              : {summary['fraud_rows']:,}".replace(",", " ")
          + f" ({summary['fraud_rate']:.2%})")
    print(f"  средняя сумма     : легальная {summary['avg_amount_legit']:.2f}"
          f" | мошенническая {summary['avg_amount_fraud']:.2f}")
    print()
    print("  Сценарии фрода:")
    for scenario, count in sorted(summary["scenarios"].items(), key=lambda item: -item[1]):
        share = count / max(1, summary["fraud_rows"])
        print(f"    {scenario:<22} {count:>6}  ({share:.1%})")
    print("=" * 72)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
