# Shin — FinTech Anti-Fraud System

> **Shin** (каз. *шын* — «правда») — система выявления и предотвращения мошеннических
> транзакций в реальном времени: ML-скоринг, Risk Score 0–100, автоматическое решение
> и объяснение, почему это решение принято.

```
Transaction -> Feature Engineering -> ML Model -> Risk Score -> Risk Engine -> Decision -> XAI Explanation
```

## Демонстрация

| | |
|---|---|
| **Интерфейс** | **<https://shin-antifraud.onrender.com>** |
| API и Swagger | <https://shin-fraud-api.onrender.com/docs> |

> Backend развёрнут на бесплатном тарифе и засыпает после простоя. Первое
> обращение сначала будит контейнер — это до минуты, интерфейс в это время
> сам объясняет, что происходит. Дальше всё отвечает мгновенно.

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

Пороги решений конфигурируемые, и главное — **видно, во что обходится выбранная
конфигурация**. Дашборд показывает компромисс прямо: сколько фрода система ловит,
скольких добросовестных клиентов при этом задевает и как эти две величины меняются
при сдвиге порога чувствительности.

Интерфейс состоит из двух экранов:

| Экран | Что показывает |
|---|---|
| **Дашборд** | весь поток транзакций: пойманный и пропущенный фрод, трение, стоимость, вклад каждой политики, кривая Fraud Loss против Customer Inconvenience |
| **Симулятор** | одна операция вручную — Risk Score, решение и объяснение за секунду |

Аналитика по датасету считается заранее скриптом
`backend/scripts/export_evaluation.py` и отдаётся через `GET /analytics/overview`:
полный проход по 100 000 транзакций занимает около двадцати секунд, и ждать
столько в запросе нельзя. Ту же картину печатает в консоль
`backend/scripts/evaluate_risk_engine.py` — оба используют один расчёт
из `app/analytics/report.py`.

---

## 2. Архитектура

### 2.1 Поток обработки запроса

```
                            ┌──────────────────────────┐
  Test Web Interface ─POST /predict─►   FastAPI (api/routes)
  (React + Vite + TS)                 └────────────┬─────────────┘
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
| **SHAP** | точные значения Шепли через `TreeExplainer` (установлен: 0.52.0) |
| **LightGBM `pred_contrib`** | те же значения Шепли без внешнего пакета — объяснения остаются точными в минимальной установке |
| **Ablation** | замена признака на эталон из данных; работает с любой моделью и объясняет итоговую вероятность |
| **Narrator** | перевод технического признака в формулировку для человека |

### 3.4 Frontend

Минимальный тестовый интерфейс: одна страница, без роутинга и графиков.

| Технология | Роль |
|---|---|
| **React 18** | UI |
| **TypeScript** | типы, зеркалящие Pydantic-схемы |
| **Vite 5** | dev-сервер и сборка |
| **обычный CSS** | без UI-фреймворков |
| **fetch** | запросы к `POST /predict` |

Frontend делает ровно одно: `Input -> POST /predict -> Display Response`.
Дублировать Risk Engine, пороги или расчёт признаков на клиенте запрещено —
такая копия разойдётся с backend и начнёт показывать не то, что система
решила на самом деле.

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
| Tailwind / MUI | интерфейс — одна страница; нужен читаемый студенту CSS |

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
│   │   ├── monitoring/             # сдвиг распределения признаков (PSI)
│   │   ├── store/                  # профили, транзакции, разметка аналитика
│   │   ├── core/                   # логирование, исключения
│   │   └── config/                 # settings.py (единый источник конфигурации)
│   ├── data/                       # датасет (raw) и разметка аналитика (feedback)
│   ├── models/                     # артефакты обученной модели
│   ├── scripts/                    # generate_dataset.py, train_model.py
│   ├── tests/                      # pytest
│   └── requirements.txt
├── frontend/                       # минимальный Test Web Interface
│   └── src/
│       ├── main.tsx                # точка входа
│       ├── App.tsx                 # одна страница целиком
│       ├── App.tsx                 # оболочка и переключение вкладок
│       ├── Dashboard.tsx           # аналитика по всему потоку
│       ├── Simulator.tsx           # одна операция и вердикт
│       ├── FeedbackPanel.tsx       # накопленная разметка аналитика
│       ├── DriftPanel.tsx          # сдвиг распределения признаков
│       ├── ShadowPanel.tsx         # вторая конфигурация: что было бы
│       ├── api.ts                  # клиент POST /predict, GET /scenarios
│       ├── types.ts                # типы, зеркалящие Pydantic-схемы
│       └── styles.css              # обычный CSS
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

Интерфейс: **<http://localhost:5173>** (или `http://127.0.0.1:5173` — работают оба).

Если backend поднят на другом адресе, скопируйте `frontend/.env.example`
в `frontend/.env` и укажите `VITE_API_URL`.

### Дашборд

Открывается первым. Показывает работу системы на всём датасете: пойманный
и пропущенный фрод, долю задетых добросовестных клиентов (False Positive Rate),
разбивку решений, вклад каждой политики и кривую компромисса с ползунком порога.

Дашборду нужен выгруженный отчёт. Если его нет, экран честно скажет об этом
и назовёт команду:

```bash
python backend/scripts/export_evaluation.py
```

Ползунок порога не меняет настройки системы — он показывает, что было бы при
другом пороге на тех же данных. Все точки кривой посчитаны заранее.

### Симулятор: что можно проверить за 10 секунд

1. открыть <http://localhost:5173>;
2. нажать кнопку сценария — форма заполнится;
3. поменять `amount`, `country`, `device_id`, `transaction_frequency`;
4. нажать **Analyze Transaction**;
5. увидеть новый Risk Score, Decision и объяснение.

Кнопки-пресетов шесть, и они берутся с `GET /scenarios` — тот же источник,
что у автотестов и [docs/HAND_TESTING.md](docs/HAND_TESTING.md), поэтому
разойтись с ними не могут.

### Обратная связь аналитика: откуда в системе берётся правда

Под вердиктом стоят две кнопки — **Вердикт верный** и **Вердикт ошибочный**.
Это не оценка интерфейса, а единственный канал, по которому в работающую
систему попадает истина.

Без неё все метрики в проде — самооценка: `GET /stats` считает долю
рискованных по собственным вердиктам и честно оговаривает, что измеренной
истиной это не является. Разметка аналитика превращает оговорку в число:
панель «Разметка аналитика» на дашборде показывает подтверждённую точность,
ложные срабатывания и пропущенный фрод — по тем операциям, которые разобрал
человек.

Спрашивать «это был фрод?» напрямую не нужно: система знает, что утверждала,
и выводит метку сама. Подтверждённый BLOCK означает фрод, подтверждённый
APPROVE — чистую операцию.

Накопленное — датасет, а не журнал кликов. Метка хранит слепок решения
(Risk Score, вердикт, сработавшие политики), потому что буфер транзакций
ограничен и к моменту дообучения самой операции в памяти уже не будет.
Метки дописываются в `backend/data/feedback/labels.jsonl` построчно: это
единственное в системе, что нельзя пересчитать заново.

```bash
curl -X POST "http://localhost:8000/transactions/txn_001/feedback" \
  -H "Content-Type: application/json" \
  -d '{"verdict": "INCORRECT", "analyst": "ops", "comment": "клиент подтвердил покупку"}'
```

Забрать накопленное целиком — `GET /feedback`. На хостинге с эфемерным
диском это единственный способ достать разметку до того, как контейнер
погаснет.

### Дрейф данных: поломка, которую больше нечем заметить

Модель обучена на сгенерированном датасете и с тех пор не менялась. Когда
живой поток перестаёт походить на обучающий, её оценки становятся
недостоверными — и **система об этом не сообщит**. Исключения нет, в логах
пусто, `/health` зелёный, ответ по-прежнему число от 0 до 100. Просто это
число уже ни о чём не говорит.

Ни тест, ни healthcheck такого не ловят. Ловит только сравнение
распределений, и панель «Сдвиг распределения» на дашборде показывает его
по каждому из 27 признаков.

Мера — Population Stability Index, привычный в скоринге: до 0.1 стабильно,
0.1–0.25 умеренный сдвиг, дальше существенный. Выбран он не только за
привычность. PSI считается по корзинам, то есть **не требует хранить
наблюдения**: в памяти живут три сотни счётчиков независимо от того,
миллион транзакций прошёл или три. Наблюдение ничего не знает о клиентах
и не растёт со временем.

Эталон снимается тем же проходом по датасету, что и аналитика
(`export_evaluation.py` пишет оба артефакта), а счётчики живут до
перезапуска: в отличие от разметки аналитика, их восстанавливает
обычный трафик.

```bash
curl "http://localhost:8000/monitoring/drift"
```

Пока наблюдений меньше двухсот, числа не называются — на полусотне
транзакций PSI меряет случайность. Режим «что если» (`persist=false`)
в наблюдение не попадает: десяток нажатий Analyze на одном сценарии
сдвинул бы картину сильнее, чем настоящий поток.

### Теневая конфигурация: проверить гипотезу, не трогая систему

Дашборд говорит неприятное: текущий порог 30 далеко от самого дешёвого
(4), а четыре политики из шести не ловят ничего сверх модели и приносят
одно трение. Но по этим числам никто не станет переключать работающую
систему, и правильно не станет — кривая отвечает, что было бы **на
обучающем датасете**.

Теневой режим отвечает на другой вопрос: что происходит **на сегодняшнем
потоке**. Вторая конфигурация видит те же настоящие операции и выносит
свои решения — и они никуда не уходят. Ответ `POST /predict` от них
не зависит ни одним полем, в историю и профиль клиента они не попадают,
деньги по ним не блокируются.

Это главное свойство, и оно закреплено тестом, который сравнивает ответ
с включённой тенью и с выключенной целиком, до последнего поля.

Панель «Теневая конфигурация» показывает матрицу «кто что решил»,
разделяет расхождения на снятое и добавленное трение и приводит
последние операции, по которым конфигурации разошлись.

```bash
curl "http://localhost:8000/monitoring/shadow"
```

Настраивается переменными `SHADOW_*`. По умолчанию тень проверяет ровно
то неприятное открытие: те же пороги, но без политик. На живом потоке
из 120 операций это дало 97.5 % совпадений и три операции, которые
политики отправили на проверку, а модель считала чистыми.

---

## 9. Запуск через Docker

```bash
docker compose up --build
```

| Сервис | URL |
|---|---|
| Test Web Interface | <http://localhost:3000> |
| Swagger через тот же адрес | <http://localhost:3000/docs> |
| Backend API напрямую | <http://localhost:8000> |
| Swagger напрямую | <http://localhost:8000/docs> |

Первая сборка занимает несколько минут: внутри образа backend генерируется
датасет на 100 000 транзакций и обучается модель. Артефакты не лежат
в репозитории, поэтому копировать их неоткуда — а без модели `/predict`
отвечал бы 503.

### Как устроена сеть

Браузер работает на машине пользователя и внутреннюю сеть Docker не видит:
адрес вроде `http://backend:8000` оттуда не резолвится. Поэтому интерфейс
собран с `VITE_API_URL=/api` и шлёт запросы на **тот же origin**, а nginx
переправляет их в контейнер backend:

```
браузер ──/api/predict──► nginx (frontend:80) ──/predict──► backend:8000
```

Завершающий слэш в `proxy_pass http://shin_backend/;` отрезает префикс `/api`.
Побочная выгода: запросы становятся одноисточниковыми, и CORS в этой схеме
не участвует вовсе.

### Полезные команды

```bash
docker compose logs -f backend
```

```bash
docker compose down
```

Пороги решений и политик меняются переменными окружения в `docker-compose.yml`
без пересборки образа.

---

## 10. Пример API request

```bash
curl -X POST http://localhost:8000/predict   -H "Content-Type: application/json"   -d @transaction.json
```

Обязательны только поля из [ТЗ §3](docs/TZ.md#3-данные-транзакции). Поля
контекста клиента (`user_avg_amount`, `known_device_ids`, `previous_*`)
опциональны: если их не передать, система возьмёт данные из профиля клиента,
накопленного предыдущими запросами. Передать их явно стоит для ручного
тестирования — тогда ответ не зависит от истории и воспроизводится.

`transaction_id` и `timestamp` можно не указывать: первый генерируется,
второй берётся как текущее время UTC.

```json
{
  "transaction_id": "txn_demo_0001",
  "user_id": "user_00042",
  "amount": 2500.0,
  "timestamp": "2026-09-01T02:14:00",
  "merchant": "Binance",
  "country": "NG",
  "device_id": "dev_unknown_77",
  "ip_address": "197.210.44.12",
  "latitude": 6.5244,
  "longitude": 3.3792,
  "transaction_frequency": 14,
  "previous_transaction_amount": 95.0,
  "previous_transaction_country": "KZ",
  "account_age_days": 800,
  "user_avg_amount": 100.0,
  "user_amount_std": 30.0,
  "user_home_country": "KZ",
  "user_typical_frequency": 3.0,
  "known_device_ids": [
    "dev_known_1",
    "dev_known_2"
  ],
  "previous_ip_address": "85.132.10.40",
  "previous_timestamp": "2026-09-01T01:52:00",
  "previous_latitude": 51.15,
  "previous_longitude": 71.4,
  "txn_count_last_hour": 8
}
```

---

## 11. Пример API response

Настоящий ответ системы на запрос выше. Полный вектор признаков и список
факторов сокращены для читаемости.

```json
{
  "transaction_id": "txn_demo_0001",
  "user_id": "user_00042",
  "timestamp": "2026-09-01T02:14:00",
  "risk_score": 100,
  "model_score": 100,
  "probability": 0.9996812002152072,
  "decision": "BLOCK",
  "risk_level": "CRITICAL",
  "raised_by_rules": false,
  "triggered_rules": [
    {
      "key": "impossible_travel",
      "title": "Impossible travel: location cannot be reached in the elapsed time",
      "min_score": 75
    },
    {
      "key": "velocity_burst",
      "title": "Abnormal transaction velocity",
      "min_score": 60
    },
    {
      "key": "high_risk_country",
      "title": "Transaction from a high-risk country",
      "min_score": 55
    },
    {
      "key": "unusual_country",
      "title": "Transaction from an unusual country on an unfamiliar connection",
      "min_score": 40
    },
    {
      "key": "new_device",
      "title": "Unrecognized device on an unrecognized network",
      "min_score": 35
    }
  ],
  "explanation": {
    "method": "shap",
    "units": "logit",
    "base_value": -8.827910490413865,
    "summary": "Risk score 100/100 resulted in BLOCK. 5 policy rule(s) applied on top of the model, and 5 model factor(s) contributed to the score.",
    "reasons": [
      "Impossible travel: location cannot be reached in the elapsed time",
      "Abnormal transaction velocity",
      "Transaction from a high-risk country",
      "Transaction from an unusual country on an unfamiliar connection",
      "Unrecognized device on an unrecognized network",
      "... всего 10"
    ],
    "policy_reasons": [
      "Impossible travel: location cannot be reached in the elapsed time",
      "Abnormal transaction velocity",
      "Transaction from a high-risk country",
      "Transaction from an unusual country on an unfamiliar connection",
      "Unrecognized device on an unrecognized network"
    ],
    "factors": [
      {
        "feature": "travel_speed_kmh",
        "value": 21601.606010876974,
        "display_value": "21602",
        "contribution": 4.06129489231958,
        "direction": "INCREASES_RISK",
        "reason": "Implied travel speed of 21602 km/h between transactions",
        "description": "Требуемая скорость перемещения между транзакциями, км/ч"
      },
      {
        "feature": "is_impossible_travel",
        "value": 1.0,
        "display_value": "yes",
        "contribution": 2.9657509074442574,
        "direction": "INCREASES_RISK",
        "reason": "Impossible travel: this location cannot be reached in the elapsed time",
        "description": "Перемещение физически невозможно за прошедшее время"
      },
      {
        "feature": "amount_zscore",
        "value": 50.0,
        "display_value": "50.0",
        "contribution": 2.6947767081768776,
        "direction": "INCREASES_RISK",
        "reason": "Amount deviates 50.0 standard deviations from the user's usual spending",
        "description": "Отклонение суммы от обычной в стандартных отклонениях клиента"
      }
    ]
  },
  "thresholds": {
    "approve_max": 30,
    "challenge_max": 70,
    "critical_min": 90
  },
  "features": {
    "amount_deviation_ratio": 25.0,
    "is_new_device": 1.0,
    "is_unusual_country": 1.0,
    "is_high_risk_country": 1.0,
    "is_impossible_travel": 1.0,
    "travel_speed_kmh": 21601.606011,
    "txn_count_last_hour": 8.0,
    "is_night": 1.0,
    "...": "всего 27 признаков"
  },
  "processing_ms": 24.08
}
```

Обратите внимание на `model_score` рядом с `risk_score`: здесь они совпали —
модель сама дала 100, политики ничего не поднимали (`raised_by_rules: false`),
хотя и сработали все пять. В сценарии «новое устройство» картина обратная:
`model_score: 1`, `risk_score: 35`.

---

## 12. Инструкция по hand-testing

Шесть сценариев ([ТЗ §9](docs/TZ.md#9-hand-testing--обязательные-сценарии)):

| # | Сценарий | Ожидание |
|---|---|---|
| 1 | Normal transaction | низкий Risk Score / `APPROVE` |
| 2 | New device | Risk Score выше, чем в сценарии 1 |
| 3 | Unusual country | повышенный риск |
| 4 | Large amount | повышенный риск |
| 5 | Multiple anomalies | высокий Risk Score / `BLOCK` |

### Фактические результаты

| # | Сценарий | Risk Score | Решение | Что подняло риск |
|---|---|---|---|---|
| 1 | Normal transaction | **0** | `APPROVE` | — |
| 2 | New device | **35** | `CHALLENGE` | политика `new_device` (модель дала 1) |
| 3 | Unusual country | **55** | `CHALLENGE` | политики `high_risk_country`, `unusual_country` (модель дала 6) |
| 4 | Large amount | **73** | `BLOCK` | **только модель**, политики не срабатывали |
| 5 | Multiple anomalies | **100** | `BLOCK` | модель 100 + пять политик |
| 6 | High frequency | **60** | `CHALLENGE` | политика `velocity_burst` (модель дала 5) |

Рост монотонный. Сценарий 4 показателен отдельно: крупную сумму распознаёт
сама модель, без помощи правил.

### Три способа прогнать

**Swagger.** Откройте <http://localhost:8000/docs>, разверните
`POST /scenarios/{key}/run`, нажмите *Try it out*, выберите сценарий, *Execute*.

**curl:**

```bash
curl -X POST "http://localhost:8000/scenarios/multiple_anomalies/run"
```

**Автотесты:**

```bash
pytest backend/tests/test_scenarios.py -v
```

Все пять сценариев описывают **одного клиента**: меняется ровно то, что заявлено
в названии, поэтому Risk Score между ними сравним. Профиль и время переданы явно,
поэтому повторный прогон даёт тот же ответ.

Полный разбор с вкладами признаков — в [docs/HAND_TESTING.md](docs/HAND_TESTING.md).
Файл **генерируется** из фактических ответов системы:

```bash
python backend/scripts/export_hand_testing.py
```

---

## 13. Описание ML-модели

| Параметр | Значение |
|---|---|
| Алгоритм | LightGBM 4.7.0 (`LGBMClassifier`, 400 деревьев, learning rate 0.05) |
| Fallback | sklearn `HistGradientBoosting`, если LightGBM недоступен |
| Признаков | 27 — см. [docs/FEATURES.md](docs/FEATURES.md) |
| Обучающая выборка | 99 360 транзакций, доля фрода 1.95 % |
| Разбиение | train / calibration / test = 60 / 20 / 20, стратифицированно |
| Дисбаланс классов | вес положительного класса = √(neg/pos) ≈ 7.1 |
| Калибровка вероятностей | sigmoid (Платт) на отдельной части выборки |
| Время обучения | ~11 с |

### Метрики на тестовой выборке (19 872 транзакции)

| Метрика | Значение |
|---|---|
| ROC-AUC | **0.991** |
| PR-AUC | **0.9148** |
| Precision (порог 0.50) | **0.9351** |
| Recall (порог 0.50) | **0.8191** |
| F1 (порог 0.50) | **0.8733** |
| Brier score | 0.003811 |
| TP / FP / FN / TN | 317 / 22 / 70 / 19 463 |

Лучший F1 достигается на пороге 0.6: **0.8748**
(precision 0.9599  recall 0.8036). Рабочий порог системы —
0.31  граница `APPROVE`/`CHALLENGE`  а не 0.50  поэтому практический recall
ближе к значению из этой строки.

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

Границы задаются в `.env` (`RISK_APPROVE_MAX`, `RISK_CHALLENGE_MAX`).
`RiskEngine` принимает пороги объектом, поэтому один и тот же поток можно
пересчитать при разных границах без перезапуска — этим пользуется
`backend/scripts/evaluate_risk_engine.py`.

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

Объяснение собирает **два независимых источника**: вклады признаков модели
и сработавшие политики Risk Engine. Показывать только первое было бы неполно:
в сценарии «новое устройство» модель даёт 1 балл, а итоговые 35 — целиком
заслуга правила.

### Движки вкладов

| Движок | Что считает | Когда используется |
|---|---|---|
| `shap` | точные значения Шепли (`shap.TreeExplainer`) | установлен пакет `shap` |
| `lightgbm_native` | те же значения Шепли, встроенные в LightGBM | `shap` не установлен |
| `ablation` | изменение вероятности при замене признака на эталон | любая модель |

Средний вариант важен: LightGBM считает TreeSHAP сам, поэтому объяснения
остаются **точными** даже без пакета `shap`, а не деградируют до приближения.
Числа обоих движков совпадают до `1e-6` — это проверяется тестом.

SHAP и встроенный расчёт объясняют логит базовой модели до калибровки;
калибровка монотонна, поэтому порядок и знак вкладов сохраняются. Единицы
измерения возвращаются в поле `units`, чтобы это не приходилось угадывать.

### Пример вывода

```
3 Unusual country   Risk Score: 55   Decision: CHALLENGE   (MEDIUM)
  Reasons:
    - Transaction from a high-risk country
    - Transaction from an unusual country on an unfamiliar connection
    - Implied travel speed of 396 km/h between transactions
    - Unusual country: transaction outside the user's home country
    - Transaction 7922 km away from the previous one
  Feature contributions (logit):
    travel_speed_kmh      = 396   +2.6998  INCREASES_RISK
    is_unusual_country    = yes   +1.0957  INCREASES_RISK
    is_high_risk_country  = yes   +0.8406  INCREASES_RISK
    geo_distance_km       = 7922  +0.7645  INCREASES_RISK
    hours_since_previous  = 20.00 -0.7203  DECREASES_RISK
```

Последняя строка показательна: «прошло 20 часов» **понижает** риск — за такое
время долететь можно. Объяснение показывает не только обвинение, но и оправдание.

---

## Скрипты проекта

Все запускаются из корня проекта.

| Скрипт | Что делает |
|---|---|
| `backend/scripts/check_setup.py` | проверяет окружение: пакеты, конфигурацию, наличие артефактов |
| `backend/scripts/generate_dataset.py` | генерирует датасет на 100 000 транзакций и валидирует его |
| `backend/scripts/train_model.py` | обучает модель, печатает метрики, сохраняет артефакт |
| `backend/scripts/evaluate_risk_engine.py` | печатает оценку порогов и политик на реальном потоке |
| `backend/scripts/export_evaluation.py` | выгружает ту же оценку в `backend/models/evaluation.json` для дашборда |
| `backend/scripts/export_features.py` | генерирует [docs/FEATURES.md](docs/FEATURES.md) из реестра признаков |
| `backend/scripts/export_hand_testing.py` | генерирует [docs/HAND_TESTING.md](docs/HAND_TESTING.md) прогоном сценариев |
| `backend/scripts/check_docs.py` | сверяет README с кодом и артефактами |

### Почему часть документации генерируется

`docs/FEATURES.md` и `docs/HAND_TESTING.md` собираются скриптами, а не пишутся
руками. Причина практическая: рукописная таблица расходится с кодом после
первого же переобучения модели — и начинает врать ровно там, где её читают
внимательнее всего.

README генерировать нельзя, это связный текст. Поэтому за ним следит
`check_docs.py`: он сверяет заявленные метрики с артефактом модели, таблицу
сценариев с `HAND_TESTING.md`, упомянутые скрипты с содержимым каталога
и ссылки с файлами на диске.

```bash
python backend/scripts/check_docs.py
```

Скрипт появился не от избытка аккуратности: метрики в README успели устареть
на три переобучения, и заметить это можно было только случайно.

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
