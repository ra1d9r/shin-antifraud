"""Выгрузка справочника признаков в документацию.

Запуск:
    python backend/scripts/export_features.py

Документ `docs/FEATURES.md` генерируется из реестра `app/features/definitions.py`,
а не пишется руками. Причина простая: список признаков меняется, а рукописные
таблицы в документации после этого начинают врать.
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.console import enable_utf8_output  # noqa: E402
from app.features.definitions import FEATURE_SPECS  # noqa: E402

enable_utf8_output()

# Соответствие признаков пунктам ТЗ §4 — единственная рукописная часть.
TZ_SECTIONS: dict[str, tuple[str, ...]] = {
    "§4.1 Отклонение суммы от обычной": (
        "amount_log", "amount_deviation_ratio", "amount_zscore",
        "amount_vs_previous_ratio", "is_round_amount", "is_micro_amount",
    ),
    "§4.2 Необычная страна": (
        "is_unusual_country", "country_changed_from_previous", "is_high_risk_country",
    ),
    "§4.3 Новый device": ("is_new_device", "known_device_count"),
    "§4.4 Изменение IP": ("ip_changed", "ip_subnet_changed"),
    "§4.5 / §4.8 Частота и количество за период": (
        "transaction_frequency", "frequency_ratio", "txn_count_last_hour", "is_high_frequency",
    ),
    "§4.6 Резкое изменение геолокации": (
        "geo_distance_km", "hours_since_previous", "travel_speed_kmh", "is_impossible_travel",
    ),
    "§4.7 Время транзакции": ("hour_of_day", "is_night", "is_weekend"),
    "§4.9 Прочее поведение": (
        "account_age_days", "is_new_account", "is_high_risk_merchant",
    ),
}

HEADER = """# Справочник признаков

> **Этот файл сгенерирован автоматически.** Не редактируйте его руками —
> измените `backend/app/features/definitions.py` и выполните:
>
> ```bash
> python backend/scripts/export_features.py
> ```

Всего признаков: **{count}**. Порядок ниже — это порядок колонок вектора,
который сохраняется вместе с моделью.
"""


def build_document() -> str:
    specs = {spec.name: spec for spec in FEATURE_SPECS}
    covered: set[str] = set()
    parts = [HEADER.format(count=len(FEATURE_SPECS))]

    for section, names in TZ_SECTIONS.items():
        parts.append(f"\n## {section}\n")
        parts.append("| # | Признак | Тип | Описание | Формулировка для XAI |")
        parts.append("|---|---|---|---|---|")
        for name in names:
            spec = specs[name]
            covered.add(name)
            index = FEATURE_SPECS.index(spec)
            kind = "флаг" if spec.is_flag else "число"
            parts.append(
                f"| {index} | `{spec.name}` | {kind} | {spec.description} | {spec.reason_high} |"
            )

    missing = [spec.name for spec in FEATURE_SPECS if spec.name not in covered]
    if missing:
        raise SystemExit(
            "Признаки не отнесены ни к одному пункту ТЗ: "
            + ", ".join(missing)
            + "\nДобавьте их в TZ_SECTIONS в backend/scripts/export_features.py"
        )

    return "\n".join(parts) + "\n"


def main() -> int:
    output = PROJECT_ROOT / "docs" / "FEATURES.md"
    output.write_text(build_document(), encoding="utf-8")
    print(f"Справочник признаков записан: {output}")
    print(f"Признаков: {len(FEATURE_SPECS)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
