"""Выгрузка результатов ручного тестирования в документацию (ТЗ §9).

Запуск:
    python backend/scripts/export_hand_testing.py

Документ `docs/HAND_TESTING.md` генерируется прогоном пяти сценариев через
настоящее приложение. Числа в нём — фактические ответы системы, а не
переписанные руками: рукописная таблица разошлась бы с кодом после первого
же переобучения модели.
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import logging  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app.config.settings import get_settings  # noqa: E402
from app.core.console import enable_utf8_output  # noqa: E402
from app.main import create_app  # noqa: E402
from app.services.scenarios import SCENARIOS  # noqa: E402

enable_utf8_output()

HEADER = """# Hand Testing — сценарии ТЗ §9

> **Этот файл сгенерирован автоматически.** Не редактируйте его руками —
> измените сценарии в `backend/app/services/scenarios.py` и выполните:
>
> ```bash
> python backend/scripts/export_hand_testing.py
> ```

Все числа ниже — фактические ответы системы, полученные прогоном сценариев
через приложение.

## Как воспроизвести

**Через Swagger.** Поднимите backend и откройте <http://localhost:8000/docs>:

```bash
uvicorn app.main:app --reload --port 8000 --app-dir backend
```

Разверните `POST /scenarios/{{key}}/run`, нажмите *Try it out*, выберите
сценарий и *Execute*.

**Через curl:**

```bash
curl -X POST "http://localhost:8000/scenarios/multiple_anomalies/run"
```

**Через автотесты:**

```bash
pytest backend/tests/test_scenarios.py -v
```

## Почему сценарии сравнимы между собой

Все пять описывают **одного и того же клиента**: обычная сумма 100, дом —
Казахстан, два известных устройства, три операции в сутки, счёту 800 дней.
Меняется ровно то, что заявлено в названии сценария.

Профиль передаётся в каждом запросе явно, а метки времени зафиксированы
абсолютными значениями. Поэтому результат не зависит ни от накопленной
истории, ни от времени запуска демонстрации.

---

## Сводка

| # | Сценарий | Ожидание по ТЗ | Risk Score | Решение | Уровень |
|---|---|---|---|---|---|
{summary}

**Проверки:**

- рост риска монотонный от сценария 1 к сценарию 5: **{monotonic}**
- сценарий 1 разрешён (`APPROVE`): **{first_approved}**
- сценарии 2–4 выше базового: **{middle_above}**
- сценарий 5 заблокирован (`BLOCK`): **{last_blocked}**

В разборе каждого сценария ниже строка «Оценка модели без правил» показывает,
что дала **только модель**, до применения политик Risk Engine. Разница между
ней и итоговым Risk Score — вклад правил.

---
"""


def _format_scenario(index: int, scenario, payload: dict) -> str:
    explanation = payload["explanation"]
    rules = payload["triggered_rules"]

    lines = [
        f"## {index}. {scenario.title} — `{scenario.key.value}`",
        "",
        scenario.description,
        "",
        f"**Ожидание по ТЗ:** {scenario.expectation}",
        "",
    ]

    if scenario.changed_from_normal:
        changed = ", ".join(f"`{field}`" for field in scenario.changed_from_normal)
        lines += [f"**Отличия от обычной транзакции:** {changed}", ""]

    lines += [
        "| Показатель | Значение |",
        "|---|---|",
        f"| Risk Score | **{payload['risk_score']}** |",
        f"| Оценка модели без правил | {payload['model_score']} |",
        f"| Вероятность фрода | {payload['probability']:.4f} |",
        f"| Decision | **`{payload['decision']}`** |",
        f"| Risk Level | `{payload['risk_level']}` |",
        f"| Поднято политиками | {'да' if payload['raised_by_rules'] else 'нет'} |",
        "",
    ]

    if rules:
        lines += ["**Сработавшие политики:**", ""]
        lines += [
            f"- `{rule['key']}` (минимум {rule['min_score']}) — {rule['title']}"
            for rule in rules
        ]
        lines.append("")
    else:
        lines += ["**Политики не сработали** — оценку целиком дала модель.", ""]

    lines += ["**Причины:**", ""]
    lines += [f"- {reason}" for reason in explanation["reasons"][:6]]
    lines.append("")

    lines += [
        f"**Вклады признаков** (`{explanation['method']}`, единицы: `{explanation['units']}`):",
        "",
        "| Признак | Значение | Вклад | Направление |",
        "|---|---|---|---|",
    ]
    for factor in explanation["factors"]:
        arrow = "повышает" if factor["direction"] == "INCREASES_RISK" else "понижает"
        lines.append(
            f"| `{factor['feature']}` | {factor['display_value']} "
            f"| {factor['contribution']:+.4f} | {arrow} |"
        )
    lines += ["", "---", ""]
    return "\n".join(lines)


def main() -> int:
    logging.disable(logging.INFO)
    settings = get_settings()

    with TestClient(create_app(settings)) as client:
        health = client.get("/health").json()
        if not health["model_loaded"]:
            print("Модель не загружена. Выполните: python backend/scripts/train_model.py")
            return 1

        results = {}
        for scenario in SCENARIOS:
            response = client.post(
                f"/scenarios/{scenario.key.value}/run", params={"persist": False}
            )
            if response.status_code != 200:
                print(f"Сценарий {scenario.key.value} вернул {response.status_code}")
                return 1
            results[scenario.key.value] = response.json()

    scores = [results[scenario.key.value]["risk_score"] for scenario in SCENARIOS]
    thresholds = results[SCENARIOS[0].key.value]["thresholds"]

    summary_rows = []
    for index, scenario in enumerate(SCENARIOS, start=1):
        payload = results[scenario.key.value]
        summary_rows.append(
            f"| {index} | {scenario.title} | {scenario.expectation} "
            f"| **{payload['risk_score']}** | `{payload['decision']}` "
            f"| `{payload['risk_level']}` |"
        )

    def yes_no(value: bool) -> str:
        return "да" if value else "НЕТ"

    document = HEADER.format(
        summary="\n".join(summary_rows),
        monotonic=yes_no(scores == sorted(scores)),
        first_approved=yes_no(scores[0] <= thresholds["approve_max"]),
        middle_above=yes_no(all(score > scores[0] for score in scores[1:4])),
        last_blocked=yes_no(scores[-1] > thresholds["challenge_max"]),
    )

    for index, scenario in enumerate(SCENARIOS, start=1):
        document += "\n" + _format_scenario(index, scenario, results[scenario.key.value])

    document += (
        "\n## Как менялся Risk Score\n\n```\n"
        + "\n".join(
            f"{index}. {scenario.title:<22} {results[scenario.key.value]['risk_score']:>3}  "
            f"{'#' * (results[scenario.key.value]['risk_score'] // 3)}"
            for index, scenario in enumerate(SCENARIOS, start=1)
        )
        + "\n```\n\nПороги: "
        f"APPROVE <= {thresholds['approve_max']} < CHALLENGE <= "
        f"{thresholds['challenge_max']} < BLOCK\n"
    )

    output = PROJECT_ROOT / "docs" / "HAND_TESTING.md"
    output.write_text(document, encoding="utf-8")

    print(f"Документ записан: {output}")
    print(f"Risk Score по сценариям: {scores}")
    print(f"Монотонный рост: {'да' if scores == sorted(scores) else 'НЕТ'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
