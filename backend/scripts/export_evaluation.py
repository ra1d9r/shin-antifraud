"""Выгрузка аналитики по всему датасету в артефакт (брифинг §5.A, §11).

Запуск:
    python backend/scripts/export_evaluation.py

## Зачем артефакт, а не расчёт на лету

Дашборду нужны величины, которые считаются по всему потоку транзакций:
сколько фрода система ловит, скольких добросовестных клиентов задевает,
во что это обходится и как меняется при сдвиге порога. Полный проход по
100 000 транзакций занимает около двадцати секунд — признаки строятся
построчно, а предельный вклад каждой политики требует отдельного прогона
движка.

Столько ждать нельзя ни на старте приложения (healthcheck не дождётся),
ни в обработчике запроса. Поэтому расчёт выполняется здесь, результат
кладётся в `backend/models/evaluation.json`, а приложение его читает.
Тот же приём, что с `model_metrics.json`.

Артефакт устаревает вместе с моделью: переобучили — выгрузите заново.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.analytics.report import build_report  # noqa: E402
from app.analytics.source import prepare_inputs  # noqa: E402
from app.config.settings import get_settings  # noqa: E402
from app.core.console import enable_utf8_output  # noqa: E402
from app.core.logging import configure_logging, get_logger  # noqa: E402
from app.risk_engine.engine import RiskThresholds  # noqa: E402

enable_utf8_output()
logger = get_logger("shin.analytics.export")


def parse_args() -> argparse.Namespace:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Выгрузка аналитики Shin для дашборда")
    parser.add_argument("--dataset", type=str, default=None, help="путь к CSV с транзакциями")
    parser.add_argument("--model", type=str, default=None, help="путь к модели")
    parser.add_argument("--output", type=str, default=None, help="куда записать JSON")
    parser.add_argument("--approve-max", type=int, default=settings.risk_approve_max)
    parser.add_argument("--challenge-max", type=int, default=settings.risk_challenge_max)
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="взять подвыборку (для быстрой проверки; по умолчанию весь датасет)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    settings = get_settings()
    configure_logging(settings.log_level)

    started = time.perf_counter()

    inputs = prepare_inputs(
        settings,
        dataset_path=Path(args.dataset).resolve() if args.dataset else None,
        model_path=Path(args.model).resolve() if args.model else None,
        limit=args.limit,
    )

    logger.info("Считаю отчёт по %s транзакциям...", f"{len(inputs.frame):,}".replace(",", " "))
    report = build_report(
        inputs.frame,
        inputs.features,
        inputs.labels,
        inputs.probabilities,
        settings=settings,
        thresholds=RiskThresholds(
            approve_max=args.approve_max,
            challenge_max=args.challenge_max,
            critical_min=settings.risk_critical_min,
        ),
        model=inputs.model,
        # Дефект 3: раньше здесь всегда стояло True, и при RULES_ENABLED=false
        # дашборд показывал статистику политик, которые не работают.
        rules_enabled=settings.rules_enabled,
    )

    output = Path(args.output).resolve() if args.output else settings.evaluation_file
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
    )

    elapsed = time.perf_counter() - started

    print()
    print("=" * 72)
    print("  Аналитика выгружена")
    print("=" * 72)
    print(f"  транзакций        : {report.rows:,}".replace(",", " "))
    print(f"  фрод остановлен   : {report.fraud_stopped}/{report.fraud_rows}"
          f" ({report.fraud_stopped_share:.1%})")
    print(f"  трение            : {report.friction}/{report.legit_rows}"
          f" ({report.friction_share:.1%})")
    print(f"  оптимальный порог : {report.optimal_threshold}"
          f" (текущий APPROVE <= {report.thresholds['approve_max']})")
    print(f"  файл              : {output}")
    print(f"  заняло            : {elapsed:.1f} с")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
