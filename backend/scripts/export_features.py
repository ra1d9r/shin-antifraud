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
    """Собрать документ, группируя по разделу из самого реестра.

    Раньше соответствие признаков пунктам ТЗ жило здесь отдельным
    списком, и новый признак можно было в него не добавить — скрипт
    ловил это проверкой и падал. Теперь раздел — обязательное поле
    признака, и забыть его нельзя: не соберётся сам реестр.
    """
    parts = [HEADER.format(count=len(FEATURE_SPECS))]

    # Документация на русском — языке проекта. Переводы отдаёт API
    # по `?language=`; дублировать их здесь значило бы завести вторую
    # копию, которая однажды разойдётся с первой.
    for section in dict.fromkeys(spec.section.ru for spec in FEATURE_SPECS):
        parts.append(f"\n## {section}\n")
        parts.append("| # | Признак | Тип | Описание | Формулировка для XAI |")
        parts.append("|---|---|---|---|---|")
        for index, spec in enumerate(FEATURE_SPECS):
            if spec.section.ru != section:
                continue
            kind = "флаг" if spec.is_flag else "число"
            parts.append(
                f"| {index} | `{spec.name}` | {kind} | {spec.description.ru} "
                f"| {spec.reason_high} |"
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
