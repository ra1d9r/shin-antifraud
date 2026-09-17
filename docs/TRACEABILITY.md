# Трассировка требований ТЗ -> код

Таблица связывает каждый пункт [ТЗ](TZ.md) с конкретными файлами реализации.
Обновляется по завершении каждого этапа. Колонка «Статус» показывает фактическое
состояние, а не план.

**Легенда:** `TODO` — не реализовано, `WIP` — частично, `DONE` — реализовано и проверено, `ОТЛОЖЕН` — выведено за рамки ревизией 2 ТЗ.

| Пункт ТЗ | Требование | Файл(ы) | Статус |
|---|---|---|---|
| §2.1 | `POST /predict` | `backend/app/api/routes/predict.py` | DONE |
| §2.1 | `GET /health` | `backend/app/api/routes/health.py` | DONE |
| §2.1 | `GET /stats` | `backend/app/api/routes/stats.py` | DONE |
| §2.1 | Swagger / OpenAPI | `backend/app/main.py` | DONE |
| §3 | Поля транзакции | `backend/app/schemas/transaction.py` | DONE |
| §4.1 | Отклонение суммы | `backend/app/features/builder.py` | DONE |
| §4.2 | Необычная страна | `backend/app/features/builder.py` | DONE |
| §4.3 | Новый device | `backend/app/features/builder.py` | DONE |
| §4.4 | Изменение IP | `backend/app/features/builder.py` | DONE |
| §4.5 | Необычная частота | `backend/app/features/builder.py` | DONE |
| §4.6 | Резкая смена геолокации | `backend/app/features/geo.py` | DONE |
| §4.7 | Время транзакции | `backend/app/features/builder.py` | DONE |
| §4.8 | Транзакции за период | `backend/app/features/builder.py` | DONE |
| §5.1 | Датасет 100k | `backend/app/ml/dataset.py`, `backend/scripts/generate_dataset.py` | DONE |
| §5.2 | Target fraud/non-fraud | `backend/app/ml/dataset.py` | DONE |
| §5.3 | Preprocessing | `backend/app/ml/pipeline.py` | DONE |
| §5.4 | Train/test split | `backend/app/ml/pipeline.py` (`split_dataset`) | DONE |
| §5.5 | Обучение модели | `backend/app/ml/pipeline.py` | DONE |
| §5 | Сохранение модели | `backend/models/fraud_model.joblib` | DONE |
| §5 | Метрики P/R/F1/ROC-AUC | `backend/app/ml/metrics.py` | DONE |
| §5 | Дисбаланс классов | `backend/app/ml/pipeline.py` (`compute_scale_pos_weight`) | DONE |
| §5 | Загрузка модели при старте | `backend/app/api/deps.py` (`build_state`), lifespan в `main.py` | DONE |
| §6 | Risk Score 0–100 | `backend/app/risk_engine/engine.py` | DONE |
| §6 | Конфигурируемые пороги | `backend/app/config/settings.py`, `risk_engine/engine.py` | DONE |
| §6 | Бизнес-правила поверх ML | `backend/app/risk_engine/rules.py` | DONE |
| §7 | XAI-модуль | `backend/app/xai/explainer.py`, `xai/contributions.py` | DONE |
| §7 | 3–5 факторов риска | `backend/app/xai/narrator.py` | DONE |
| ~~§8.1~~ | ~~Overview~~ | отложено ревизией 2 (ТЗ §8.5); backend `GET /stats` готов | ОТЛОЖЕН |
| ~~§8.2~~ | ~~Таблица транзакций + фильтры~~ | отложено ревизией 2 (ТЗ §8.5); backend `GET /transactions` готов | ОТЛОЖЕН |
| §8.2 | Transaction Simulator (форма 14 полей) | `frontend/src/App.tsx` | DONE |
| §8.3 | Result: score, decision, reasons, XAI, сырой JSON | `frontend/src/App.tsx` | DONE |
| §8.4 | Шесть кнопок-пресетов | `frontend/src/App.tsx` + `GET /scenarios` | DONE |
| §9 | Сценарий `high_frequency` (шестой, решение D-9) | `backend/app/services/scenarios.py` | DONE |
| §9 | Сценарии hand-testing | `backend/app/services/scenarios.py`, `api/routes/scenarios.py`, `docs/HAND_TESTING.md` | DONE |
| ~~§10~~ | ~~Business Cost~~ | отложено ревизией 2; расчёт есть в `scripts/evaluate_risk_engine.py` | ОТЛОЖЕН |
| §12 | `.env.example` | `.env.example` | DONE |
| §12 | CORS | `backend/app/main.py` | DONE |
| §12 | `requirements.txt` | `backend/requirements.txt` | DONE |
| §13 | Dockerfile backend | `docker/backend.Dockerfile` | DONE |
| §13 | Dockerfile frontend | `docker/frontend.Dockerfile`, `docker/nginx.conf` | DONE |
| §13 | docker-compose | `docker-compose.yml` | WIP — файл написан, запуск не прогонялся (Docker отсутствует, D-6) |
| §14 | README (15 разделов) | `README.md`, сверка `backend/scripts/check_docs.py` | DONE |
