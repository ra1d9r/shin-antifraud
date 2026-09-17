# Shin — План этапов разработки

Мастер-документ по этапам из [ТЗ §16](TZ.md#16-порядок-работы-этапы).
Каждый этап имеет: **цель**, **артефакты** (что появляется на диске), **DoD**
(Definition of Done — как проверяем, что этап действительно закрыт) и **статус**.

Отчёт по завершённому этапу пишется в `docs/stages/stage-NN-<slug>.md`.

**Легенда статусов:** `TODO` — не начат, `WIP` — в работе, `DONE` — закрыт и проверен.

> **Отступление от порядка ТЗ §16.** Этап 05 (Feature Engineering) выполнен
> раньше этапов 03–04 (ML pipeline). Причина техническая: pipeline обучения
> вызывает тот же модуль признаков, что и API, — это архитектурное требование,
> исключающее training/serving skew. Обучать модель до появления признаков
> было бы невозможно.

---

## Сводная таблица

| # | Этап | Статус | Отчёт |
|---|---|---|---|
| 01 | Структура проекта | `DONE` | [stage-01](stages/stage-01-project-structure.md) |
| 02 | Synthetic dataset (100k) | `DONE` | [stage-02](stages/stage-02-synthetic-dataset.md) |
| 03 | ML training pipeline | `DONE` | [stage-03-04](stages/stage-03-04-ml-pipeline.md) |
| 04 | Обучение и сохранение модели | `DONE` | [stage-03-04](stages/stage-03-04-ml-pipeline.md) |
| 05 | Feature Engineering | `DONE` | [stage-05](stages/stage-05-feature-engineering.md) |
| 06 | Risk Engine | `DONE` | [stage-06](stages/stage-06-risk-engine.md) |
| 07 | XAI | `DONE` | [stage-07](stages/stage-07-xai.md) |
| 08 | FastAPI | `DONE` | [stage-08](stages/stage-08-fastapi.md) |
| 09 | Проверка API через Swagger | `DONE` | [stage-09](stages/stage-09-swagger-hand-testing.md) |
| 10 | Test Web Interface (React + Vite + TS) | `DONE` | [stage-10](stages/stage-10-test-web-interface.md) |
| 11 | Simulator подключён к реальному `/predict` | `DONE` | [stage-10](stages/stage-10-test-web-interface.md) |
| ~~12~~ | ~~Dashboard (Overview + Transactions)~~ | `ОТЛОЖЕН` | ТЗ §8.5 |
| ~~13~~ | ~~Business Cost~~ | `ОТЛОЖЕН` | ТЗ §10 |
| 14 | Docker | `DONE` | [stage-14](stages/stage-14-docker.md) |
| 15 | README | `TODO` | — |
| 16 | Финальная проверка сценариев | `TODO` | — |

---

## Этап 01 — Структура проекта

**Цель.** Каркас репозитория, окружение, конфигурация, базовые контракты —
чтобы все последующие этапы писали код в готовые места, а не изобретали их.

**Артефакты.**
- дерево каталогов `backend/` + `frontend/` + `docs/` + `docker/`;
- `backend/requirements.txt`, `backend/requirements-optional.txt`;
- `.env.example`, `.gitignore`;
- `backend/app/config/settings.py` — единая типизированная конфигурация;
- `backend/app/core/` — логирование и доменные исключения;
- `backend/app/schemas/` — Pydantic-контракты (enum'ы решений и уровней риска);
- `docs/TZ.md`, `docs/STAGES.md`, `docs/TRACEABILITY.md`, `README.md`;
- `.venv` с установленными зависимостями.

**DoD.**
1. `python -c "from app.config.settings import get_settings; print(get_settings())"` отрабатывает.
2. Импорт всех пакетов `app.*` не падает.
3. `pip list` содержит fastapi, pydantic, numpy, pandas, scikit-learn.
4. Пороги Risk Score читаются из конфигурации, а не из кода.

---

## Этап 02 — Synthetic dataset

**Цель.** Демонстрационный датасет ~100 000 транзакций с реалистичной структурой
поведения клиентов и внедрёнными паттернами фрода.

**Артефакты.**
- `backend/app/ml/dataset.py` — генератор;
- `backend/scripts/generate_dataset.py` — CLI-скрипт;
- `backend/data/raw/transactions.csv`.

**Ключевые решения.**
- сначала генерируются **профили клиентов** (домашняя страна, обычная сумма,
  список устройств, IP-подсеть, координаты), затем — их транзакции;
- фрод не «подкрашивается меткой», а **порождается сценариями**
  (account takeover, card testing, geo-impossible travel, new-device cashout, ...);
- целевая доля фрода ~1.5–3 % — реалистичный дисбаланс;
- в данные намеренно вносится шум, чтобы модель не была тривиально разделимой.

**DoD.**
1. CSV содержит ~100 000 строк и все поля из [ТЗ §3](TZ.md#3-данные-транзакции).
2. `is_fraud` присутствует, доля фрода в диапазоне 1–5 %.
3. Генерация детерминирована при фиксированном `seed`.

---

## Этап 03 — ML training pipeline

**Цель.** Воспроизводимый pipeline: сырой CSV -> признаки -> train/test -> модель -> метрики.

**Артефакты.**
- `backend/app/ml/pipeline.py` — препроцессинг + сборка модели;
- `backend/app/ml/metrics.py` — precision / recall / F1 / ROC-AUC / PR-AUC;
- `backend/scripts/train_model.py` — training script.

**Ключевые решения.**
- **один и тот же** модуль feature engineering используется и в обучении, и в API —
  это исключает training/serving skew;
- дисбаланс классов: `class_weight` / `scale_pos_weight` + стратифицированный split;
- выбор алгоритма: LightGBM, иначе sklearn `HistGradientBoosting`, иначе `GradientBoosting`.

**DoD.**
1. `python scripts/train_model.py` проходит от начала до конца.
2. В консоль печатаются precision, recall, F1, ROC-AUC на test.
3. ROC-AUC заметно выше 0.5 (целевой ориентир >= 0.90).

---

## Этап 04 — Обучение и сохранение модели

**Цель.** Артефакт модели, который API загружает при старте.

**Артефакты.**
- `backend/models/fraud_model.joblib` — модель + метаданные (список признаков, версия, метрики);
- `backend/models/model_metrics.json` — метрики для отображения в API/Dashboard.

**DoD.**
1. Файл модели существует и загружается через `joblib.load`.
2. Сохранён порядок признаков — предсказание на одной транзакции повторяемо.
3. Повторный запуск обучения перезаписывает артефакт без ошибок.

---

## Этап 05 — Feature Engineering

**Цель.** Отдельный модуль, превращающий транзакцию + профиль клиента в вектор признаков.
Никакой связи с FastAPI.

**Артефакты.**
- `backend/app/features/builder.py` — построение признаков;
- `backend/app/features/definitions.py` — реестр признаков (имя, описание, человекочитаемая формулировка);
- `backend/app/features/geo.py` — расстояние по haversine, скорость перемещения.

**Покрытие [ТЗ §4](TZ.md#4-feature-engineering).**

Полный перечень признаков — в [docs/FEATURES.md](FEATURES.md). Этот файл
**генерируется** из реестра командой `python backend/scripts/export_features.py`,
поэтому не может разойтись с кодом.

| Требование ТЗ | Признаков |
|---|---|
| §4.1 отклонение суммы | 6 |
| §4.2 необычная страна | 3 |
| §4.3 новый device | 2 |
| §4.4 изменение IP | 2 |
| §4.5 / §4.8 частота и количество за период | 4 |
| §4.6 резкая смена геолокации | 4 |
| §4.7 время транзакции | 3 |
| §4.9 прочее поведение | 3 |
| **итого** | **27** |

**DoD.**
1. Модуль импортируется без FastAPI.
2. На одной и той же транзакции возвращает одинаковый вектор.
3. Каждый признак имеет описание в реестре (нужно для XAI).

---

## Этап 06 — Risk Engine

**Цель.** Превращение вероятности модели в Risk Score 0–100 и в решение.
Пороги — из конфигурации.

**Артефакты.**
- `backend/app/risk_engine/engine.py` — score + decision;
- `backend/app/risk_engine/rules.py` — жёсткие бизнес-правила поверх ML (например, невозможное перемещение поднимает риск независимо от модели).

**DoD.**
1. Пороги меняются через `.env` / `PATCH /config/thresholds` без правки кода.
2. `probability=0.0 -> score=0`, `probability=1.0 -> score=100`.
3. Решение строго соответствует настроенным диапазонам.

---

## Этап 07 — XAI

**Цель.** Объяснение каждого решения: 3–5 факторов риска и вклад каждого.

**Артефакты.**
- `backend/app/xai/contributions.py` — три движка вкладов (SHAP, встроенный LightGBM, ablation);
- `backend/app/xai/explainer.py` — отбор топ-факторов и сборка объяснения;
- `backend/app/xai/narrator.py` — перевод признака в человеческую формулировку.

**DoD.**
1. В ответе `/predict` не менее 3 и не более 5 факторов.
2. У каждого фактора есть направление (повышает / понижает риск) и величина вклада.
3. При изменении входа меняется и состав факторов.

---

## Этап 08 — FastAPI

**Цель.** HTTP-слой: только валидация, вызов сервиса и сериализация ответа.

**Артефакты.**
- `backend/app/main.py`, `backend/app/api/routes/*.py`;
- `backend/app/services/prediction_service.py` — оркестрация цепочки;
- `backend/app/store/` — in-memory хранилище транзакций и профилей клиентов.

**DoD.**
1. `GET /health` возвращает статус и факт загрузки модели.
2. `POST /predict` отрабатывает полную цепочку.
3. `GET /stats` считает реальную статистику по обработанным транзакциям.
4. CORS открыт для frontend.

---

## Этап 09 — Проверка API через Swagger

**Цель.** Убедиться, что API тестируется руками без клиента.

**DoD.**
1. `/docs` открывается, схемы читаемы.
2. Все 5 сценариев из [ТЗ §9](TZ.md#9-hand-testing--обязательные-сценарии) прогоняются через Swagger.
3. Risk Score реально меняется при изменении входа.

---

## Этап 10 — Test Web Interface

> **Переопределён ревизией 2 ТЗ (2026-09-17).** Раньше здесь был полноценный
> frontend с тёмной темой и роутингом. Теперь — минимальный инструмент
> ручного тестирования: одна страница, никакой аналитики и графиков.

**Цель.** Одна страница React + Vite + TypeScript, которая даёт за 10 секунд
поменять параметры транзакции и увидеть новый ответ системы.

**Артефакты.**
- `frontend/` целиком: `package.json`, `vite.config.ts`, `index.html`, `tsconfig.json`;
- `src/App.tsx` — страница;
- `src/api.ts` — клиент `POST /predict`;
- `src/types.ts` — типы, зеркалящие Pydantic-схемы;
- `src/styles.css` — обычный CSS.

Файла `scenarios.ts` нет: пресеты берутся с `GET /scenarios`, чтобы
не заводить четвёртую копию сценариев рядом с backend, автотестами
и `docs/HAND_TESTING.md`.

**Ключевые решения.**
- frontend делает только `Input -> POST /predict -> Display Response`;
- **запрещено** дублировать Risk Engine, пороги и расчёт признаков на клиенте;
- никаких mock-данных: только реальные ответы API.

**DoD.**
1. `npm run build` проходит без ошибок TypeScript.
2. Форма содержит все 14 полей ТЗ §3.
3. Результат показывает Risk Score, Decision, Risk Level, причины,
   feature contributions и сырой JSON.
4. Шесть кнопок-пресетов заполняют форму, значения остаются редактируемыми.

---

## Этап 11 — Проверка связки вживую

**Цель.** Убедиться, что цепочка работает от браузера до модели, а не только
в тестах.

**Артефакты.** Шестой сценарий `high_frequency` в
`backend/app/services/scenarios.py` (ТЗ §9, решение D-9).

**DoD.**
1. Backend и frontend подняты одновременно, CORS не мешает.
2. Все шесть пресетов отрабатывают через реальный `POST /predict`.
3. Изменение `amount`, `country`, `device_id`, `transaction_frequency`
   вручную приводит к **новому** ответу backend.
4. Ошибки API (422, 503, недоступный backend) показываются человеку,
   а не молча теряются.

---

## ~~Этап 12 — Dashboard~~ *(отложен)*

Выведен за рамки работы ревизией 2 ТЗ. Требования сохранены в
[ТЗ §8.5](TZ.md#85-отложено-полноценный-dashboard).

Backend готов: `GET /stats` и `GET /transactions` с фильтрами работают
и покрыты тестами.

---

## ~~Этап 13 — Business Cost~~ *(отложен)*

Выведен за рамки работы ревизией 2 ТЗ. Требования сохранены в
[ТЗ §10](TZ.md#10-business-cost--отложено).

Частично уже сделано: параметры стоимости заданы в `.env`, а расчёт
реализован в `backend/scripts/evaluate_risk_engine.py` — он сравнивает
чистый ML с ML + политики. Не хватает HTTP-эндпоинта и экрана.

---

## Этап 14 — Docker

**Цель.** `docker compose up --build` поднимает backend + frontend.

**Артефакты.** `docker/backend.Dockerfile`, `docker/frontend.Dockerfile`,
`docker/nginx.conf`, `docker-compose.yml`, `.dockerignore`.

**Ключевые решения.**
- модель обучается на этапе сборки: артефактов нет в репозитории, копировать нечего;
- `VITE_API_URL=/api` — браузер не видит сеть Docker, запросы идут на тот же
  origin, nginx проксирует их на backend; CORS в этой схеме не участвует;
- `libgomp1` обязателен: без него LightGBM не импортируется на slim-образе.

**DoD.** Dockerfile'ы самодостаточны: обучение модели выполняется на этапе сборки образа,
если артефакт отсутствует.

> Docker на машине разработки отсутствует ([D-6](TZ.md#отклонения-и-решения)),
> поэтому `docker compose up --build` не прогонялся. Схема сети проверена
> заглушкой nginx на Python — подробности в отчёте этапа.

---

## Этап 15 — README

**Цель.** 15 обязательных разделов из [ТЗ §14](TZ.md#14-readme--обязательные-разделы).

**DoD.** Человек, впервые открывший репозиторий, запускает проект по README без вопросов.

---

## Этап 16 — Финальная проверка

**Цель.** Прогон всех сценариев end-to-end и фиксация фактических чисел.

**Артефакты.** `backend/tests/`, `docs/HAND_TESTING.md` с реальными ответами API.

**DoD.**
1. `pytest` зелёный.
2. Risk Score монотонно растёт от сценария 1 к сценарию 5.
3. Все числа в документации — настоящие ответы системы, а не выдуманные.
