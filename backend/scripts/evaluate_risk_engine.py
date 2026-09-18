"""Оценка Risk Engine на реальном потоке транзакций (ТЗ §6).

Запуск:
    python backend/scripts/evaluate_risk_engine.py
    python backend/scripts/evaluate_risk_engine.py --no-rules   # чистый ML

Скрипт отвечает на вопросы, которые нельзя проверить по одной транзакции:

* как распределяются решения APPROVE / CHALLENGE / BLOCK;
* сколько добросовестных клиентов задевает каждая политика;
* сколько фрода ловится и сколько проходит;
* что именно меняют правила по сравнению с чистым выходом модели.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import pandas as pd  # noqa: E402

from app.config.settings import get_settings  # noqa: E402
from app.core.console import enable_utf8_output  # noqa: E402
from app.core.exceptions import DatasetNotFoundError, ModelNotLoadedError  # noqa: E402
from app.core.logging import configure_logging, get_logger  # noqa: E402
from app.ml.dataset import generate_dataset  # noqa: E402
from app.ml.pipeline import load_model, prepare_training_data  # noqa: E402
from app.risk_engine import RiskEngine, RiskThresholds  # noqa: E402
from app.risk_engine.rules import build_rules, evaluate_rules  # noqa: E402
from app.schemas.enums import Decision  # noqa: E402

enable_utf8_output()
logger = get_logger("shin.risk_engine.eval")

DATE_COLUMNS = ["timestamp", "previous_timestamp"]


def parse_args() -> argparse.Namespace:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Оценка Risk Engine на датасете")
    parser.add_argument("--dataset", type=str, default=None)
    parser.add_argument("--model", type=str, default=None)
    parser.add_argument("--no-rules", action="store_true", help="оценить чистый выход ML")
    parser.add_argument("--approve-max", type=int, default=settings.risk_approve_max)
    parser.add_argument("--challenge-max", type=int, default=settings.risk_challenge_max)
    parser.add_argument("--limit", type=int, default=30_000, help="сколько транзакций взять")
    return parser.parse_args()


def _print_decision_table(title: str, decisions: list[Decision], labels) -> dict:
    """Распределение решений отдельно по легальным и мошенническим."""
    counts: Counter = Counter()
    for decision, is_fraud in zip(decisions, labels, strict=True):
        counts[(decision, int(is_fraud))] += 1

    legit_total = int((labels == 0).sum())
    fraud_total = int((labels == 1).sum())

    print(f"\n  {title}")
    print(f"    {'решение':<12}{'легальные':>14}{'фрод':>16}")
    print("    " + "-" * 42)
    summary = {}
    for decision in (Decision.APPROVE, Decision.CHALLENGE, Decision.BLOCK):
        legit = counts[(decision, 0)]
        fraud = counts[(decision, 1)]
        summary[decision.value] = {"legit": legit, "fraud": fraud}
        print(
            f"    {decision.value:<12}"
            f"{legit:>8} ({legit / max(1, legit_total):>5.1%})"
            f"{fraud:>9} ({fraud / max(1, fraud_total):>5.1%})"
        )
    return summary


def main() -> int:
    args = parse_args()
    settings = get_settings()
    configure_logging(settings.log_level)

    dataset_path = Path(args.dataset).resolve() if args.dataset else settings.dataset_file
    model_path = Path(args.model).resolve() if args.model else settings.model_file

    if not dataset_path.exists():
        if args.dataset:
            # Путь назвали явно — значит, ждали именно его. Молча создать
            # вместо него другой файл было бы хуже, чем отказать.
            logger.error("%s", DatasetNotFoundError(f"Датасет не найден: {dataset_path}").message)
            return 1

        # Путь по умолчанию. Внутри Docker-образа CSV удаляется сразу после
        # обучения — он весит 25 МБ и иначе навсегда остался бы в истории
        # слоёв. Поэтому там этот скрипт просто не запускался.
        #
        # Восстанавливаем датасет тем же генератором и тем же зерном.
        # Данные получаются ровно те, на которых обучалась модель:
        # генерация детерминирована, и это закреплено тестом
        # test_dataset.py::test_generation_is_deterministic_across_processes.
        logger.info(
            "Датасет не найден (%s) — генерирую заново с зерном %s",
            dataset_path,
            settings.random_seed,
        )
        restored = generate_dataset(
            rows=settings.dataset_rows,
            users=settings.dataset_users,
            fraud_rate=settings.dataset_fraud_rate,
            seed=settings.random_seed,
        )
        dataset_path.parent.mkdir(parents=True, exist_ok=True)
        restored.to_csv(dataset_path, index=False)
    if not model_path.exists():
        logger.error(
            "%s",
            ModelNotLoadedError(
                f"Модель не найдена: {model_path}. "
                "Выполните: python backend/scripts/train_model.py"
            ).message,
        )
        return 1

    frame = pd.read_csv(dataset_path, parse_dates=DATE_COLUMNS)
    if args.limit and len(frame) > args.limit:
        frame = frame.sample(args.limit, random_state=0).reset_index(drop=True)

    features, labels = prepare_training_data(frame)
    model = load_model(model_path)
    probabilities = model.predict_proba(features)

    thresholds = RiskThresholds(
        approve_max=args.approve_max,
        challenge_max=args.challenge_max,
        critical_min=settings.risk_critical_min,
    )
    engine = RiskEngine(
        thresholds=thresholds,
        rules=build_rules(settings),
        rules_enabled=not args.no_rules,
    )

    records = features.to_dict(orient="records")
    assessments = [
        engine.assess(probability, row)
        for probability, row in zip(probabilities, records, strict=True)
    ]

    print()
    print("=" * 72)
    print("  Risk Engine — оценка на потоке транзакций")
    print("=" * 72)
    print(f"  транзакций        : {len(frame):,}".replace(",", " "))
    print(f"  из них фрод       : {int(labels.sum())} ({labels.mean():.2%})")
    print(f"  пороги            : APPROVE <= {thresholds.approve_max}"
          f" < CHALLENGE <= {thresholds.challenge_max} < BLOCK")
    print(f"  правила           : {'выключены' if args.no_rules else 'включены'}")

    _print_decision_table(
        "Решения" + (" (чистый ML)" if args.no_rules else " (ML + политики)"),
        [item.decision for item in assessments],
        labels,
    )

    # --- эффективность
    fraud_total = int(labels.sum())
    blocked_fraud = sum(
        1 for item, y in zip(assessments, labels, strict=True)
        if y == 1 and item.decision is Decision.BLOCK
    )
    caught_fraud = sum(
        1 for item, y in zip(assessments, labels, strict=True)
        if y == 1 and item.decision is not Decision.APPROVE
    )
    missed_fraud = fraud_total - caught_fraud
    legit_total = int((labels == 0).sum())
    friction = sum(
        1 for item, y in zip(assessments, labels, strict=True)
        if y == 0 and item.decision is not Decision.APPROVE
    )

    print("\n  Итог:")
    print(
        f"    фрод заблокирован        : {blocked_fraud}/{fraud_total} "
        f"({blocked_fraud / max(1, fraud_total):.1%})"
    )
    print(
        f"    фрод остановлен вообще   : {caught_fraud}/{fraud_total} "
        f"({caught_fraud / max(1, fraud_total):.1%})"
    )
    print(
        f"    фрод пропущен            : {missed_fraud}/{fraud_total} "
        f"({missed_fraud / max(1, fraud_total):.1%})"
    )
    print(f"    трение у добросовестных  : {friction}/{legit_total} ({friction / max(1, legit_total):.1%})")

    # --- вклад каждой политики
    if not args.no_rules:
        rules = build_rules(settings)
        legit_hits: Counter = Counter()
        fraud_hits: Counter = Counter()
        for row, y in zip(records, labels, strict=True):
            for rule in evaluate_rules(rules, row):
                (fraud_hits if y == 1 else legit_hits)[rule.key] += 1

        print("\n  Срабатывание политик:")
        print(f"    {'политика':<26}{'мин.балл':>9}{'легальные':>14}{'фрод':>14}{'точность':>11}")
        print("    " + "-" * 74)
        for rule in rules:
            legit = legit_hits[rule.key]
            fraud = fraud_hits[rule.key]
            precision = fraud / max(1, legit + fraud)
            print(
                f"    {rule.key:<26}{rule.min_score:>9}"
                f"{legit:>7} ({legit / max(1, legit_total):>5.1%})"
                f"{fraud:>7} ({fraud / max(1, fraud_total):>5.1%})"
                f"{precision:>10.1%}"
            )

        # --- предельный вклад: что политика меняет СВЕРХ того, что уже сделал ML.
        # Срабатывание на транзакции, которую модель и так остановила, ценности
        # не добавляет — а трение у добросовестных клиентов добавляет всегда.
        bare = RiskEngine(thresholds=thresholds, rules=(), rules_enabled=False)
        bare_assessments = [
            bare.assess(probability, row)
            for probability, row in zip(probabilities, records, strict=True)
        ]

        print("\n  Предельный вклад политик (сверх решения чистого ML):")
        print(f"    {'политика':<26}{'+поймано фрода':>16}{'+трение':>11}{'цена за 1 фрод':>18}")
        print("    " + "-" * 73)

        for rule in rules:
            solo = RiskEngine(thresholds=thresholds, rules=(rule,), rules_enabled=True)
            gained_fraud = 0
            added_friction = 0
            for base, probability, row, y in zip(
                bare_assessments, probabilities, records, labels, strict=True
            ):
                if base.decision is not Decision.APPROVE:
                    continue
                if solo.assess(probability, row).decision is not Decision.APPROVE:
                    if y == 1:
                        gained_fraud += 1
                    else:
                        added_friction += 1
            price = (
                f"{added_friction / gained_fraud:.0f} проверок"
                if gained_fraud else "— (ноль пользы)"
            )
            print(f"    {rule.key:<26}{gained_fraud:>16}{added_friction:>11}{price:>18}")

        raised = sum(1 for item in assessments if item.raised_by_rules)
        print(f"\n    оценка поднята политиками: {raised} транзакций")

        # --- денежная оценка по модели стоимости из .env
        def total_cost(items) -> float:
            cost = 0.0
            for item, amount, y in zip(items, frame["amount"], labels, strict=True):
                if y == 1 and item.decision is Decision.APPROVE:
                    cost += amount * settings.cost_fraud_loss_ratio + settings.cost_fraud_fixed
                elif y == 0 and item.decision is Decision.BLOCK:
                    cost += settings.cost_false_block
                elif y == 0 and item.decision is Decision.CHALLENGE:
                    cost += settings.cost_false_challenge
            return cost

        with_rules_cost = total_cost(assessments)
        without_rules_cost = total_cost(bare_assessments)
        delta = with_rules_cost - without_rules_cost

        print("\n  Бизнес-стоимость (параметры из .env):")
        print(f"    чистый ML      : {without_rules_cost:>12,.0f}".replace(",", " "))
        print(f"    ML + политики  : {with_rules_cost:>12,.0f}".replace(",", " "))
        verdict = "политики окупаются" if delta < 0 else "политики дороже, чем экономят"
        print(f"    разница        : {delta:>+12,.0f}   -> {verdict}".replace(",", " "))

    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
