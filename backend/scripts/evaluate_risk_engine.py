"""Оценка Risk Engine на реальном потоке транзакций (ТЗ §6).

Запуск:
    python backend/scripts/evaluate_risk_engine.py
    python backend/scripts/evaluate_risk_engine.py --no-rules   # чистый ML

Скрипт отвечает на вопросы, которые нельзя проверить по одной транзакции:

* как распределяются решения APPROVE / CHALLENGE / BLOCK;
* сколько добросовестных клиентов задевает каждая политика;
* сколько фрода ловится и сколько проходит;
* что именно меняют правила по сравнению с чистым выходом модели.

Сам расчёт живёт в `app/analytics/report.py` — здесь только печать.
Это разделение появилось вместе с дашбордом: те же величины нужны
и в консоли, и по HTTP, а две копии одной формулы расходятся.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.analytics.report import DatasetReport, build_report  # noqa: E402
from app.analytics.source import prepare_inputs  # noqa: E402
from app.config.settings import get_settings  # noqa: E402
from app.core.console import enable_utf8_output  # noqa: E402
from app.core.exceptions import ModelNotLoadedError  # noqa: E402
from app.core.logging import configure_logging, get_logger  # noqa: E402
from app.risk_engine.engine import RiskThresholds  # noqa: E402

enable_utf8_output()
logger = get_logger("shin.risk_engine.eval")


def parse_args() -> argparse.Namespace:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Оценка Risk Engine Shin")
    parser.add_argument("--dataset", type=str, default=None)
    parser.add_argument("--model", type=str, default=None)
    parser.add_argument("--no-rules", action="store_true", help="оценить чистый выход ML")
    parser.add_argument("--approve-max", type=int, default=settings.risk_approve_max)
    parser.add_argument("--challenge-max", type=int, default=settings.risk_challenge_max)
    parser.add_argument("--limit", type=int, default=30_000, help="сколько транзакций взять")
    return parser.parse_args()


def _print_decisions(report: DatasetReport, title: str) -> None:
    """Распределение решений отдельно по легальным и мошенническим."""
    print(f"\n  {title}")
    print(f"    {'решение':<12}{'легальные':>14}{'фрод':>16}")
    print("    " + "-" * 42)
    for row in report.decisions:
        print(
            f"    {row.decision:<12}"
            f"{row.legit:>8} ({row.legit / max(1, report.legit_rows):>5.1%})"
            f"{row.fraud:>9} ({row.fraud / max(1, report.fraud_rows):>5.1%})"
        )


def _print_rules(report: DatasetReport) -> None:
    print("\n  Срабатывание политик:")
    print(f"    {'политика':<26}{'мин.балл':>9}{'легальные':>14}{'фрод':>14}{'точность':>11}")
    print("    " + "-" * 74)
    for rule in report.rules:
        print(
            f"    {rule.key:<26}{rule.min_score:>9}"
            f"{rule.legit_hits:>7} ({rule.legit_hits / max(1, report.legit_rows):>5.1%})"
            f"{rule.fraud_hits:>7} ({rule.fraud_hits / max(1, report.fraud_rows):>5.1%})"
            f"{rule.precision:>10.1%}"
        )

    print("\n  Предельный вклад политик (сверх решения чистого ML):")
    print(f"    {'политика':<26}{'+поймано фрода':>16}{'+трение':>11}{'цена за 1 фрод':>18}")
    print("    " + "-" * 73)
    for rule in report.rules:
        price = (
            "— (ноль пользы)"
            if rule.checks_per_fraud is None
            else f"{rule.checks_per_fraud:.0f} проверок"
        )
        print(f"    {rule.key:<26}{rule.gained_fraud:>16}{rule.added_friction:>11}{price:>18}")

    print(f"\n    оценка поднята политиками: {report.raised_by_rules} транзакций")


def _print_cost(report: DatasetReport) -> None:
    print("\n  Бизнес-стоимость (параметры из .env):")
    print(f"    чистый ML      : {report.cost_without_rules:>12,.0f}".replace(",", " "))
    print(f"    ML + политики  : {report.cost_with_rules:>12,.0f}".replace(",", " "))
    verdict = (
        "политики окупаются"
        if report.rules_cost_delta < 0
        else "политики дороже, чем экономят"
    )
    print(f"    разница        : {report.rules_cost_delta:>+12,.0f}   -> {verdict}".replace(",", " "))

    best = min(report.curve, key=lambda point: point.total_cost)
    current = report.thresholds["approve_max"]
    print("\n  Порог чувствительности (всё выше порога уходит на проверку):")
    print(f"    текущий APPROVE <= {current}")
    print(f"    дешевле всего      : порог {best.threshold}"
          f" — пропущено {best.fraud_missed} фрода, задето {best.friction} клиентов")


def main() -> int:
    args = parse_args()
    settings = get_settings()
    configure_logging(settings.log_level)

    try:
        inputs = prepare_inputs(
            settings,
            dataset_path=Path(args.dataset).resolve() if args.dataset else None,
            model_path=Path(args.model).resolve() if args.model else None,
            limit=args.limit,
        )
    except (FileNotFoundError, ModelNotLoadedError) as exc:
        logger.error("%s", getattr(exc, "message", str(exc)))
        return 1

    thresholds = RiskThresholds(
        approve_max=args.approve_max,
        challenge_max=args.challenge_max,
        critical_min=settings.risk_critical_min,
    )
    report = build_report(
        inputs.frame,
        inputs.features,
        inputs.labels,
        inputs.probabilities,
        settings=settings,
        thresholds=thresholds,
        model=inputs.model,
        rules_enabled=not args.no_rules,
    )

    print()
    print("=" * 72)
    print("  Risk Engine — оценка на потоке транзакций")
    print("=" * 72)
    print(f"  транзакций        : {report.rows:,}".replace(",", " "))
    print(f"  из них фрод       : {report.fraud_rows} ({report.fraud_rate:.2%})")
    print(f"  пороги            : APPROVE <= {thresholds.approve_max}"
          f" < CHALLENGE <= {thresholds.challenge_max} < BLOCK")
    print(f"  правила           : {'выключены' if args.no_rules else 'включены'}")

    _print_decisions(
        report, "Решения" + (" (чистый ML)" if args.no_rules else " (ML + политики)")
    )

    print("\n  Итог:")
    print(f"    фрод заблокирован        : {report.fraud_blocked}/{report.fraud_rows} "
          f"({report.fraud_blocked / max(1, report.fraud_rows):.1%})")
    print(f"    фрод остановлен вообще   : {report.fraud_stopped}/{report.fraud_rows} "
          f"({report.fraud_stopped_share:.1%})")
    print(f"    фрод пропущен            : {report.fraud_missed}/{report.fraud_rows} "
          f"({report.fraud_missed / max(1, report.fraud_rows):.1%})")
    print(f"    трение у добросовестных  : {report.friction}/{report.legit_rows} "
          f"({report.friction_share:.1%})")

    if report.rules:
        _print_rules(report)
        _print_cost(report)

    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
