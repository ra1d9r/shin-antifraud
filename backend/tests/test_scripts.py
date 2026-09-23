"""Тесты скриптов из `backend/scripts`.

Скрипты были единственной частью проекта, которую не покрывал ни один тест,
хотя именно они создают датасет и обучают модель. Сломанный скрипт
обнаружился бы при ручном запуске — или, что хуже, во время `docker build`,
который выполняет `generate_dataset.py` и `train_model.py` внутри образа.

Проверяются три разных свойства:

* **каждый скрипт импортируется** — параметризация идёт по содержимому
  каталога, поэтому новый скрипт попадает под проверку сам, без правки
  этого файла;
* **цепочка работает целиком** — generate -> train -> evaluate на крошечных
  данных, где каждый шаг читает то, что записал предыдущий;
* **генерируемая документация не устарела** — `docs/FEATURES.md` собирается
  из реестра признаков, и расхождение ловится здесь, а не при чтении.

Модель и метрики проекта тесты не трогают: скриптам передаётся `--output`
во временный каталог, а `train_model.py` кладёт `model_metrics.json`
рядом с моделью, то есть тоже во временный.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

from app.services.scenarios import SCENARIOS

BACKEND_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = BACKEND_DIR / "scripts"
PROJECT_ROOT = BACKEND_DIR.parent

SCRIPT_NAMES = sorted(path.name for path in SCRIPTS_DIR.glob("*.py"))


def run_script(name: str, *args: str) -> subprocess.CompletedProcess[str]:
    """Запустить скрипт так же, как его запускает человек или Dockerfile."""
    return subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / name), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=900,
        check=False,
    )


def load_script(name: str) -> ModuleType:
    """Импортировать скрипт как модуль.

    Безопасно: во всех скриптах `main()` вызывается под `if __name__ ==
    "__main__"`, поэтому импорт не запускает работу — только определения.
    """
    spec = importlib.util.spec_from_file_location(f"shin_script_{name[:-3]}", SCRIPTS_DIR / name)
    assert spec is not None and spec.loader is not None, name
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ------------------------------------------------------------------ импорт


def test_scripts_directory_is_not_empty() -> None:
    """Страховка параметризации: пустой каталог не должен выглядеть как успех."""
    assert SCRIPT_NAMES, "в backend/scripts нет ни одного .py — проверки ниже ничего не проверят"


@pytest.mark.parametrize("name", SCRIPT_NAMES)
def test_script_imports_and_exposes_main(name: str) -> None:
    """Опечатка в импорте или в имени функции ловится здесь, а не при запуске."""
    module = load_script(name)

    assert hasattr(module, "main"), f"{name}: нет функции main()"


# ----------------------------------------------------------------- цепочка


def test_pipeline_scripts_run_end_to_end(tmp_path: Path) -> None:
    """generate -> train -> evaluate: ровно та последовательность, что в Dockerfile.

    Данные намеренно крошечные: проверяется, что шаги стыкуются друг
    с другом и читают то, что записал предыдущий, а не качество модели —
    за него отвечает `test_pipeline.py`.
    """
    dataset = tmp_path / "transactions.csv"
    model = tmp_path / "fraud_model.joblib"

    generated = run_script(
        "generate_dataset.py", "--rows", "3000", "--users", "150", "--output", str(dataset)
    )
    assert generated.returncode == 0, generated.stdout + generated.stderr
    assert dataset.exists(), "generate_dataset.py завершился успешно, но CSV не появился"

    trained = run_script("train_model.py", "--dataset", str(dataset), "--output", str(model))
    assert trained.returncode == 0, trained.stdout + trained.stderr
    assert model.exists(), "train_model.py завершился успешно, но модель не сохранена"
    assert (tmp_path / "model_metrics.json").exists(), "метрики не записаны рядом с моделью"

    evaluated = run_script(
        "evaluate_risk_engine.py",
        "--dataset", str(dataset),
        "--model", str(model),
        "--limit", "500",
    )
    assert evaluated.returncode == 0, evaluated.stdout + evaluated.stderr


def test_check_setup_confirms_environment() -> None:
    """`check_setup.py` — первый шаг README: он обязан подтверждать готовность."""
    result = run_script("check_setup.py")

    assert result.returncode == 0, result.stdout + result.stderr


# --------------------------------------------- свежесть генерируемых документов


def test_features_doc_matches_registry() -> None:
    """`docs/FEATURES.md` генерируется из реестра — значит, обязан ему соответствовать.

    Тест ловит две ситуации сразу: реестр признаков изменили, а документ
    не перегенерировали; и наоборот — документ поправили руками, и правка
    исчезнет при следующей генерации.
    """
    generated = load_script("export_features.py").build_document()
    on_disk = (PROJECT_ROOT / "docs" / "FEATURES.md").read_text(encoding="utf-8")

    assert generated == on_disk, (
        "docs/FEATURES.md разошёлся с реестром признаков. "
        "Выполните: python backend/scripts/export_features.py"
    )


def test_hand_testing_doc_covers_every_scenario() -> None:
    """Каждый сценарий из кода должен присутствовать в сгенерированном документе."""
    document = (PROJECT_ROOT / "docs" / "HAND_TESTING.md").read_text(encoding="utf-8")
    missing = [scenario.key.value for scenario in SCENARIOS if scenario.key.value not in document]

    assert not missing, (
        f"в docs/HAND_TESTING.md нет сценариев: {missing}. "
        "Выполните: python backend/scripts/export_hand_testing.py"
    )


def test_hand_testing_generator_still_builds_a_document() -> None:
    """Генератор обязан собирать документ, а не только существовать.

    Проверка на готовый файл этого не ловит: он лежит на диске с прошлой
    выгрузки и проходит любые проверки, пока скрипт под ним падает.
    Ровно так и случилось — смена типа описаний сценариев на `Text`
    сломала генератор, а тесты остались зелёными.

    Поэтому вызывается именно сборка раздела: это те строки, которые
    подставляют описание и ожидание в текст.
    """
    module = load_script("export_hand_testing.py")
    payload = {
        "risk_score": 55,
        "model_score": 25,
        "probability": 0.5,
        "decision": "CHALLENGE",
        "risk_level": "MEDIUM",
        "raised_by_rules": True,
        "triggered_rules": [],
        "explanation": {
            "method": "shap",
            "units": "logit",
            "reasons": ["New device detected"],
            "factors": [
                {
                    "feature": "is_new_device",
                    "display_value": "yes",
                    "contribution": 1.5,
                    "direction": "INCREASES_RISK",
                }
            ],
        },
    }

    for index, scenario in enumerate(SCENARIOS, start=1):
        section = module._format_scenario(index, scenario, payload)

        assert scenario.description.ru in section
        assert scenario.expectation.ru in section
        # Объект вместо строки выглядел бы именно так.
        assert "Text(" not in section, f"{scenario.key.value}: в документ попал объект"


def test_hand_testing_doc_counts_scenarios_correctly() -> None:
    """Число в тексте не должно спорить с таблицей под ним.

    В шаблоне стояло «Все пять описывают одного клиента», а строк
    в сводке было шесть.
    """
    document = (PROJECT_ROOT / "docs" / "HAND_TESTING.md").read_text(encoding="utf-8")
    module = load_script("export_hand_testing.py")

    assert f"Все {module._count_word(len(SCENARIOS))} описывают" in document
