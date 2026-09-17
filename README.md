# Shin — FinTech Anti-Fraud System

> **Shin** (каз. *шын* — «правда») — система выявления и предотвращения мошеннических
> транзакций в реальном времени: ML-скоринг, Risk Score 0–100, автоматическое решение
> и объяснение, почему это решение принято.

```
Transaction -> Feature Engineering -> ML Model -> Risk Score -> Risk Engine -> Decision -> XAI Explanation
```

---

## 1. Описание проекта

Shin принимает финансовую транзакцию, обогащает её поведенческими признаками
на основе профиля клиента, прогоняет через обученную ML-модель, переводит вероятность
фрода в **Risk Score (0–100)** и принимает одно из трёх решений:

| Decision | Risk Score | Что происходит |
|---|---|---|
| `APPROVE` | 0–30 | транзакция проходит |
| `CHALLENGE` | 31–70 | требуется 2FA / дополнительная проверка |
| `BLOCK` | 71–100 | транзакция блокируется |

Ключевое отличие от «чёрного ящика»: **каждое решение объясняется**. Система возвращает
3–5 главных факторов риска с величиной и направлением вклада каждого — это то, что
антифрод-аналитик может прочитать, а комплаенс — защитить перед регулятором.

Пороги решений конфигурируемые, а встроенный модуль **Business Cost** показывает,
во что эти пороги обходятся бизнесу: потери от пропущенного фрода против потерь
от ложных блокировок.

---

## 2. Архитектура

### 2.1 Поток обработки запроса

```
                            ┌──────────────────────────┐
  React Dashboard  ──POST /predict──►   FastAPI (api/routes)
  (Vite + TS)                         └────────────┬─────────────┘
        ▲                                          │ Pydantic-валидация
        │                                          ▼
        │                              PredictionService (services/)
        │                                          │  оркестрация
        │              ┌───────────────────────────┼───────────────────────────┐
        │              ▼                           ▼                           ▼
        │      UserProfileStore            FeatureBuilder                 ModelRegistry
        │      (история клиента)           (features/)                    (ml/loader)
        │              │                           │                           │
        │              └──────────► feature vector ┴──────► probability ◄──────┘
        │                                          │
        │                                          ▼
        │                                   RiskEngine (risk_engine/)
        │                                   score 0–100 + decision
        │                                          │
        │                                          ▼
        │                                   Explainer (xai/)
        │                                   вклады признаков + текст
        │                                          │
        └──────────────── JSON response ◄──────────┘
```

### 2.2 Слои и зона ответственности

| Слой | Каталог | Отвечает за | Не знает о |
|---|---|---|---|
| **API** | `backend/app/api/` | HTTP, валидация, коды ошибок | ML, бизнес-правилах |
| **Services** | `backend/app/services/` | оркестрация цепочки, работа с хранилищем | HTTP |
| **Features** | `backend/app/features/` | превращение транзакции в вектор признаков | FastAPI, ML-модели |
| **ML** | `backend/app/ml/` | датасет, обучение, загрузка модели, метрики | HTTP, Risk Score |
| **Risk Engine** | `backend/app/risk_engine/` | probability -> score -> decision, бизнес-правила | FastAPI |
| **XAI** | `backend/app/xai/` | вклады признаков и человекочитаемые причины | HTTP |
| **Business** | `backend/app/business/` | Fraud Loss / Customer Inconvenience / Total Cost | HTTP |
| **Config** | `backend/app/config/` | типизированные настройки из `.env` | всё остальное |

Принцип: **feature engineering живёт в одном модуле и используется и при обучении,
и при инференсе**. Это исключает training/serving skew — классическую причину, по которой
прототип показывает хорошие метрики на тесте и разваливается в проде.

---

## 3. Технологический стек

### 3.1 Backend

| Технология | Версия | Роль в проекте |
|---|---|---|
| **Python** | 3.11+ (проверено на 3.14) | язык backend |
| **FastAPI** | >=0.115 | REST API, автоматический OpenAPI/Swagger |
| **Uvicorn** | >=0.30 | ASGI-сервер |
| **Pydantic** | v2 | схемы запросов/ответов, валидация, type safety |
| **pydantic-settings** | >=2.4 | конфигурация из `.env` с типами |
| **python-dotenv** | >=1.0 | загрузка переменных окружения |

### 3.2 Data & Machine Learning

| Технология | Роль |
|---|---|
| **NumPy** | векторные вычисления, генерация датасета |
| **pandas** | работа с табличными данными, CSV |
| **scikit-learn** | препроцессинг, split, метрики, baseline-модели |
| **joblib** | сериализация обученной модели |
| **LightGBM** | основной градиентный бустинг (установлен: 4.7.0) |

**Стратегия выбора модели** (см. [D-2](docs/TZ.md#отклонения-и-решения)):

```
LightGBM  ->  (если недоступен)  sklearn HistGradientBoostingClassifier
```

`GradientBoostingClassifier` доступен третьим вариантом по явному флагу
`--algorithm gradient_boosting`. Система всегда обучает **настоящую** модель —
никаких случайных заглушек, это проверяется тестом `test_model_is_not_a_random_stub`.

### 3.3 Explainable AI

| Технология | Роль |
|---|---|
| **SHAP** | точные Shapley-вклады признаков через `TreeExplainer` (установлен: 0.52.0) |
| **Встроенный explainer** | fallback, если SHAP недоступен: вклады на основе структуры деревьев |
| **Narrator** | перевод технического признака в формулировку для человека |

### 3.4 Frontend

| Технология | Роль |
|---|---|
| **React 18** | UI |
| **TypeScript** | типы, общие с контрактами API |
| **Vite 5** | dev-сервер и сборка |
| **React Router** | навигация между Overview / Transactions / Simulator / Business Cost |
| **Recharts** | графики Risk Score и Business Cost |
| **CSS Modules / plain CSS** | тёмная тема без тяжёлых UI-фреймворков |

### 3.5 Инфраструктура и качество

| Технология | Роль |
|---|---|
| **Docker + docker compose** | запуск всего проекта одной командой |
| **Nginx** | раздача собранного frontend в контейнере |
| **pytest + httpx** | тесты API и сценариев hand-testing |

### 3.6 Что сознательно НЕ используется

| Отказались | Почему |
|---|---|
| PostgreSQL / Redis | для hackathon-демо достаточно in-memory store; БД добавляет инфраструктуру, не добавляя ценности демонстрации |
| Kafka / очереди | прототип синхронный: «ввёл транзакцию — увидел решение» |
| Auth / JWT | демо-стенд без чувствительных данных; см. «Возможные улучшения» |
| Tailwind / MUI | лишний вес для 4 страниц; нужен читаемый студенту CSS |

---

## 4. Структура проекта

```
Shin/
├── backend/
│   ├── app/
│   │   ├── main.py                 # точка входа FastAPI, CORS, lifespan
│   │   ├── api/
│   │   │   ├── deps.py             # зависимости (модель, хранилище, настройки)
│   │   │   └── routes/             # predict / health / stats / transactions / ...
│   │   ├── schemas/                # Pydantic-контракты (request/response/enums)
│   │   ├── services/               # PredictionService, сценарии hand-testing
│   │   ├── features/               # feature engineering (builder, definitions, geo)
│   │   ├── ml/                     # dataset, pipeline, metrics, loader
│   │   ├── risk_engine/            # score, decision, бизнес-правила
│   │   ├── xai/                    # explainer + narrator
│   │   ├── business/               # модель бизнес-стоимости
│   │   ├── store/                  # in-memory профили клиентов и транзакции
│   │   ├── core/                   # логирование, исключения
│   │   └── config/                 # settings.py (единый источник конфигурации)
│   ├── data/                       # сгенерированный датасет (raw / processed)
│   ├── models/                     # артефакты обученной модели
│   ├── scripts/                    # generate_dataset.py, train_model.py
│   ├── tests/                      # pytest
│   └── requirements.txt
├── frontend/
│   └── src/
│       ├── components/             # переиспользуемые UI-блоки
│       ├── pages/                  # Overview / Transactions / Simulator / BusinessCost
│       ├── services/               # типизированный API-клиент
│       ├── types/                  # TS-типы, зеркалящие Pydantic-схемы
│       ├── hooks/                  # загрузка данных
│       └── styles/                 # тема
├── docs/
│   ├── TZ.md                       # ТЗ — source of truth
│   ├── STAGES.md                   # план и статус этапов
│   ├── TRACEABILITY.md             # требование -> файл
│   ├── HAND_TESTING.md             # сценарии с реальными ответами API
│   └── stages/                     # отчёты по закрытым этапам
├── docker/
│   ├── backend.Dockerfile
│   ├── frontend.Dockerfile
│   └── nginx.conf
├── docker-compose.yml
├── .env.example
└── README.md
```

---

## 5. Установка зависимостей

> Требуется Python 3.11+ и Node.js 18+.

### Backend

```bash
python -m venv .venv
```

Активация — Windows PowerShell:

```bash
.venv\Scripts\Activate.ps1
```

Активация — Linux / macOS:

```bash
source .venv/bin/activate
```

Установка пакетов:

```bash
pip install -r backend/requirements.txt
```

Опционально (ускоренный бустинг и точный SHAP; проект работает и без них):

```bash
pip install -r backend/requirements-optional.txt
```

Конфигурация:

```bash
cp .env.example .env
```

### Frontend

```bash
cd frontend && npm install
```

---

## 6. Запуск ML training

Генерация синтетического датасета на 100 000 транзакций:

```bash
python backend/scripts/generate_dataset.py --rows 100000 --seed 42
```

Обучение модели и сохранение артефакта:

```bash
python backend/scripts/train_model.py
```

Обе команды печатают отчёт и завершаются с ненулевым кодом, если результат
непригоден: генератор — при провале валидации данных, обучение — если
сохранённая модель предсказывает иначе, чем обученная, или если ROC-AUC
ниже 0.7.

Полезные флаги обучения:

```bash
python backend/scripts/train_model.py --algorithm hist_gradient_boosting --calibration isotonic
```

Проверить окружение и наличие артефактов:

```bash
python backend/scripts/check_setup.py
```

*Разделы 7–12 и 15 README дополняются фактическими командами и примерами
ответов по мере закрытия этапов — см. [docs/STAGES.md](docs/STAGES.md).
Все числа в документации — настоящие ответы системы, а не плановые.*

---

## 7. Запуск backend

```bash
uvicorn app.main:app --reload --port 8000 --app-dir backend
```

| URL | Что там |
|---|---|
| http://localhost:8000/docs | Swagger UI — ручное тестирование транзакций |
| http://localhost:8000/redoc | ReDoc |
| http://localhost:8000/health | health-check |

---

## 8. Запуск frontend

```bash
cd frontend && npm run dev
```

Dashboard: http://localhost:5173

---

## 9. Запуск через Docker

```bash
docker compose up --build
```

| Сервис | URL |
|---|---|
| Frontend Dashboard | http://localhost:3000 |
| Backend API | http://localhost:8000 |
| Swagger | http://localhost:8000/docs |

---

## 10. Пример API request

*Будет заполнен на этапе 09 реальным телом запроса.*

---

## 11. Пример API response

*Будет заполнен на этапе 09 реальным ответом системы.*

---

## 12. Инструкция по hand-testing

Пять обязательных сценариев ([ТЗ §9](docs/TZ.md#9-hand-testing--обязательные-сценарии)):

| # | Сценарий | Ожидание |
|---|---|---|
| 1 | Normal transaction | низкий Risk Score / `APPROVE` |
| 2 | New device | Risk Score выше, чем в сценарии 1 |
| 3 | Unusual country | повышенный риск |
| 4 | Large amount | повышенный риск |
| 5 | Multiple anomalies | высокий Risk Score / `BLOCK` |

Каждый сценарий доступен: кнопкой-пресетом в Simulator, эндпоинтом `GET /scenarios`
и автотестом в `backend/tests/`. Фактические значения — в [docs/HAND_TESTING.md](docs/HAND_TESTING.md).

---

## 13. Описание ML-модели

| Параметр | Значение |
|---|---|
| Алгоритм | LightGBM 4.7.0 (`LGBMClassifier`, 400 деревьев, learning rate 0.05) |
| Fallback | sklearn `HistGradientBoosting`, если LightGBM недоступен |
| Признаков | 27 — см. [docs/FEATURES.md](docs/FEATURES.md) |
| Обучающая выборка | 99 360 транзакций, доля фрода 1.97 % |
| Разбиение | train / calibration / test = 60 / 20 / 20, стратифицированно |
| Дисбаланс классов | вес положительного класса = √(neg/pos) ≈ 7.1 |
| Калибровка вероятностей | sigmoid (Платт) на отдельной части выборки |
| Время обучения | ~11 с |

### Метрики на тестовой выборке (19 872 транзакции)

| Метрика | Значение |
|---|---|
| ROC-AUC | **0.9959** |
| PR-AUC | **0.9233** |
| Precision (порог 0.50) | **0.9619** |
| Recall (порог 0.50) | **0.7749** |
| F1 (порог 0.50) | **0.8584** |
| Brier score | 0.00409 |
| TP / FP / FN / TN | 303 / 12 / 88 / 19 469 |

PR-AUC указан рядом с ROC-AUC намеренно: при доле фрода около 2 % именно он
честно показывает качество, тогда как ROC-AUC на сильном дисбалансе всегда
выглядит близким к единице.

Актуальные метрики всегда лежат в `backend/models/model_metrics.json` —
файл перезаписывается при каждом обучении.

### Почему вероятности калибруются

Risk Score считается как `probability × 100`, поэтому вероятность обязана быть
настоящей вероятностью. Взвешивание редкого класса систематически завышает
её, а калибровка на отложенной выборке возвращает физический смысл: среди
транзакций с Risk Score около 65 действительно около 65 % мошеннических.

Метод — **sigmoid**, а не isotonic: изотоническая регрессия на этой задаче
вырождается в ступеньку и выдаёт почти только 0 или 100, из-за чего полоса
`CHALLENGE` становится недостижимой. Подробности — в
[отчёте этапов 03–04](docs/stages/stage-03-04-ml-pipeline.md).

---

## 14. Описание Risk Score

`Risk Score = round(probability * 100)`, где `probability` — вероятность фрода от модели,
скорректированная жёсткими бизнес-правилами Risk Engine.

| Risk Score | Risk Level | Decision |
|---|---|---|
| 0–30 | `LOW` | `APPROVE` |
| 31–70 | `MEDIUM` | `CHALLENGE` |
| 71–100 | `HIGH` | `BLOCK` |

Границы задаются в `.env` (`RISK_APPROVE_MAX`, `RISK_CHALLENGE_MAX`) и меняются
в рантайме через API — endpoint порогов используется страницей Business Cost,
чтобы показать влияние порогов на стоимость решений.

### Слой бизнес-правил

Поверх модели работают жёсткие политики. Каждая задаёт **минимальный** Risk
Score при срабатывании: правила только поднимают оценку и никогда не снижают.

| Политика | Условие | Мин. балл |
|---|---|---|
| `impossible_travel` | перемещение физически недостижимо за прошедшее время | 75 |
| `velocity_burst` | ≥ 6 операций за час | 60 |
| `new_account_large_amount` | новый счёт **и** сумма ≥ 4× обычной | 60 |
| `high_risk_country` | страна из списка повышенного риска | 55 |
| `unusual_country` | чужая страна **и** (новое устройство **или** новая сеть) | 40 |
| `new_device` | новое устройство **и** новая сеть | 35 |

Условия составные намеренно. Одиночные («любая чужая страна», «любое новое
устройство») отправляли на проверку 10.2 % добросовестных клиентов, почти не
добавляя пойманного фрода — модель ловила его и без них. Составные условия
снизили трение до 2.0 %. Измерения — в
[отчёте этапа 06](docs/stages/stage-06-risk-engine.md).

Ответ API содержит и `model_score` (чистый выход модели), и `risk_score`
(после правил), поэтому всегда видно, что подняло риск:

```
Scenario            ML   итог   решение     политика
New device           1     35   CHALLENGE   new_device
Large amount        73     73   BLOCK       — (сработала только модель)
```

Проверить конфигурацию на реальном потоке:

```bash
python backend/scripts/evaluate_risk_engine.py
```

Отключить правила целиком и увидеть чистый ML: `RULES_ENABLED=false` в `.env`
или флаг `--no-rules` у скрипта.

---

## 15. Описание XAI

Для каждой транзакции считаются вклады признаков в итоговую вероятность.
Если установлен SHAP — используются Shapley-значения (`TreeExplainer`); если нет —
встроенный explainer на основе структуры деревьев. Результат один и тот же по смыслу:
знак вклада показывает направление (повышает/понижает риск), модуль — силу.

Топ-5 признаков по модулю вклада переводятся модулем `narrator` в человеческие
формулировки, например:

```
Risk Score: 87
Decision: BLOCK
Reasons:
  - Transaction amount is 12.4x higher than user's normal amount   (+0.31)
  - New device detected                                            (+0.18)
  - Unusual country: transaction from KZ, user usually pays from DE (+0.14)
  - High transaction frequency: 14 transactions in last hour        (+0.09)
```

---

## Документация проекта

| Документ | Назначение |
|---|---|
| [docs/TZ.md](docs/TZ.md) | техническое задание, source of truth |
| [docs/STAGES.md](docs/STAGES.md) | 16 этапов: цель, артефакты, DoD, статус |
| [docs/TRACEABILITY.md](docs/TRACEABILITY.md) | каждое требование ТЗ -> конкретный файл |
| [docs/stages/](docs/stages/) | отчёты по закрытым этапам |

---

## Лицензия

Hackathon-прототип. Не предназначен для обработки реальных платёжных данных.
