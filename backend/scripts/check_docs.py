"""Проверка документации на расхождение с фактами (ТЗ §14).

Запуск:
    python backend/scripts/check_docs.py

## Зачем

README — рукописный документ, и числа в нём устаревают молча. Именно так
и вышло: метрики модели попали в README на этапе 03–04 и остались там после
того, как модель трижды переобучалась. Документ уверенно сообщал
ROC-AUC 0.9959, тогда как модель давала 0.9910.

Опасность не в самой неточности, а в том, что заметить её можно только
случайно. Этот скрипт сверяет README с источниками правды и завершается
с ненулевым кодом при расхождении — то есть превращает молчаливое
устаревание в громкую ошибку.

## Что сверяется

| Утверждение в README | Источник правды |
|---|---|
| метрики модели | `backend/models/model_metrics.json` |
| результаты сценариев | `docs/HAND_TESTING.md` (генерируемый) |
| число признаков | реестр `app/features/definitions.py` |
| число сценариев | `app/services/scenarios.py` |
| упомянутые скрипты | файлы в `backend/scripts/` |
| обязательные разделы | ТЗ §14 |
| разделы «Финальной выдачи» | ТЗ, список финальной выдачи |
| ссылки вида «см. „Раздел“» | заголовки самого README |
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.console import enable_utf8_output  # noqa: E402
from app.features.definitions import FEATURE_NAMES  # noqa: E402
from app.services.scenarios import SCENARIOS  # noqa: E402

enable_utf8_output()

OK = "[ OK ]"
FAIL = "[FAIL]"

REQUIRED_SECTIONS = [
    "Описание проекта",
    "Архитектура",
    "стек",
    "Структура проекта",
    "Установка зависимостей",
    "Запуск ML training",
    "Запуск backend",
    "Запуск frontend",
    "Запуск через Docker",
    "Пример API request",
    "Пример API response",
    "Инструкция по hand-testing",
    "Описание ML-модели",
    "Описание Risk Score",
    "Описание XAI",
]


def check_sections(readme: str) -> list[str]:
    """Все 15 обязательных разделов ТЗ §14 на месте."""
    headings = re.findall(r"^## \d+\.\s*(.+)$", readme, re.M)
    problems = []

    for index, expected in enumerate(REQUIRED_SECTIONS):
        if index >= len(headings):
            problems.append(f"нет раздела {index + 1} «{expected}»")
        elif expected.lower() not in headings[index].lower():
            problems.append(
                f"раздел {index + 1}: ожидалось «{expected}», найдено «{headings[index]}»"
            )
    return problems


#: Ненумерованные разделы, которые требует «Финальная выдача» ТЗ.
#: Отдельным списком, потому что §14 их не нумерует, а `check_sections`
#: сверяет именно нумерованные — и «Возможные улучшения» когда-то
#: выпал из README, хотя ссылки на него в тексте остались.
REQUIRED_EXTRA_SECTIONS = [
    "Возможные улучшения",
    "Документация проекта",
]


def check_extra_sections(readme: str) -> list[str]:
    """Разделы из «Финальной выдачи», которые §14 не нумерует."""
    headings = re.findall(r"^##\s+(.+)$", readme, re.M)
    return [
        f"нет раздела «{expected}»"
        for expected in REQUIRED_EXTRA_SECTIONS
        if not any(expected.lower() in heading.lower() for heading in headings)
    ]


def check_section_references(readme: str) -> list[str]:
    """Ссылки вида «см. „Название“» ведут в существующий раздел.

    Дважды ссылаться на раздел, которого нет, — ровно то, что случилось
    с «Возможными улучшениями»: текст обещал подробности, а идти
    за ними было некуда.
    """
    headings = [h.lower() for h in re.findall(r"^#{2,3}\s+(.+)$", readme, re.M)]
    problems = []
    for name in set(re.findall(r"«([А-ЯЁ][^»]{4,40})»", readme)):
        # Ссылка — это упоминание рядом со словом «см.» или «раздел».
        if not re.search(rf"(см\.|раздел[еа]?)\s*«{re.escape(name)}»", readme):
            continue
        if not any(name.lower() in heading for heading in headings):
            problems.append(f"ссылка на «{name}» — такого раздела нет")
    return sorted(problems)


def check_metrics(readme: str) -> list[str]:
    """Метрики в README совпадают с сохранённым артефактом модели."""
    path = PROJECT_ROOT / "backend" / "models" / "model_metrics.json"
    if not path.exists():
        return [f"нет файла метрик {path.name} — выполните train_model.py"]

    payload = json.loads(path.read_text(encoding="utf-8"))
    metrics = payload["metrics"]
    problems = []

    for label, value in (
        ("ROC-AUC", metrics["roc_auc"]),
        ("PR-AUC", metrics["pr_auc"]),
        ("Precision", metrics["precision"]),
        ("Recall", metrics["recall"]),
        ("F1", metrics["f1"]),
    ):
        if str(value) not in readme:
            problems.append(f"метрика {label}: в артефакте {value}, в README её нет")

    if payload["algorithm"] not in readme.lower():
        problems.append(f"алгоритм {payload['algorithm']} не упомянут")

    return problems


def check_scenarios(readme: str) -> list[str]:
    """Таблица сценариев в README совпадает с генерируемым HAND_TESTING.md."""
    path = PROJECT_ROOT / "docs" / "HAND_TESTING.md"
    if not path.exists():
        return ["нет docs/HAND_TESTING.md — выполните export_hand_testing.py"]

    hand = path.read_text(encoding="utf-8")
    rows = re.findall(
        r"^\| (\d) \| ([^|]+?) \| [^|]+ \| \*\*(\d+)\*\* \| `(\w+)` \|", hand, re.M
    )
    problems = []

    if len(rows) != len(SCENARIOS):
        problems.append(
            f"в HAND_TESTING.md {len(rows)} сценариев, в коде {len(SCENARIOS)}"
        )

    for number, title, score, decision in rows:
        pattern = rf"\| {number} \| {re.escape(title.strip())} \| \*\*{score}\*\* \| `{decision}`"
        if not re.search(pattern, readme):
            problems.append(
                f"сценарий {number} «{title.strip()}»: {score}/{decision} — в README другое значение"
            )
    return problems


def check_counts(readme: str) -> list[str]:
    """Числовые утверждения о составе системы."""
    problems = []

    if f"{len(FEATURE_NAMES)} — см." not in readme and f"**{len(FEATURE_NAMES)}**" not in readme:
        problems.append(f"число признаков ({len(FEATURE_NAMES)}) не упомянуто")

    word = {5: "Пять", 6: "Шесть", 7: "Семь"}.get(len(SCENARIOS))
    if word and word.lower() not in readme.lower():
        problems.append(f"число сценариев ({len(SCENARIOS)}, «{word}») не упомянуто")

    return problems


def check_scripts(readme: str) -> list[str]:
    """Команды README ведут на существующие файлы, и наоборот."""
    problems = []

    mentioned = set(re.findall(r"backend/scripts/(\w+\.py)", readme))
    existing = {path.name for path in (BACKEND_DIR / "scripts").glob("*.py")}

    for name in sorted(mentioned - existing):
        problems.append(f"README ссылается на несуществующий скрипт {name}")
    for name in sorted(existing - mentioned - {"check_docs.py"}):
        problems.append(f"скрипт {name} есть в проекте, но не упомянут в README")

    return problems


def check_links(readme: str) -> list[str]:
    """Локальные ссылки ведут на существующие файлы."""
    problems = []
    for target in re.findall(r"\]\((?!https?:)([^)#]+)", readme):
        path = PROJECT_ROOT / target.strip()
        if not path.exists():
            problems.append(f"битая ссылка на {target}")
    return problems


def main() -> int:
    readme_path = PROJECT_ROOT / "README.md"
    readme = readme_path.read_text(encoding="utf-8")

    checks = [
        ("Обязательные разделы ТЗ §14", check_sections),
        ("Разделы «Финальной выдачи»", check_extra_sections),
        ("Ссылки на разделы", check_section_references),
        ("Метрики модели", check_metrics),
        ("Результаты сценариев", check_scenarios),
        ("Числа о составе системы", check_counts),
        ("Упомянутые скрипты", check_scripts),
        ("Ссылки на файлы", check_links),
    ]

    print("=" * 72)
    print("  Сверка README с фактическим состоянием проекта")
    print("=" * 72)

    total = 0
    for title, check in checks:
        problems = check(readme)
        total += len(problems)
        print(f"\n{OK if not problems else FAIL} {title}")
        for problem in problems:
            print(f"       - {problem}")

    print()
    print("=" * 72)
    if total == 0:
        print("  РЕЗУЛЬТАТ: README соответствует коду и артефактам")
        print("=" * 72)
        return 0

    print(f"  РЕЗУЛЬТАТ: расхождений — {total}")
    print("  README нужно привести в соответствие с источниками правды.")
    print("=" * 72)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
