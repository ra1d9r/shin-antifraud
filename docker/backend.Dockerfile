# Backend Shin: FastAPI + обученная ML-модель.
#
# Образ самодостаточен: датасет генерируется и модель обучается на этапе
# сборки. Артефакты не лежат в репозитории (`.gitignore` исключает CSV
# и `.joblib`), поэтому копировать их неоткуда — а без модели `/predict`
# отвечал бы 503.
#
# Сборка выполняется из корня проекта:
#   docker build -f docker/backend.Dockerfile -t shin-backend .

FROM python:3.12-slim AS base

# libgomp1 нужен LightGBM в рантайме: без него импорт падает с
# "libgomp.so.1: cannot open shared object file". На slim-образах его нет.
# curl — для HEALTHCHECK.
RUN apt-get update \
    && apt-get install --no-install-recommends -y libgomp1 curl \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Зависимости отдельным слоем: он переиспользуется, пока не менялись
# requirements, и не пересобирается на каждую правку кода.
COPY backend/requirements.txt backend/requirements-optional.txt ./backend/
RUN pip install -r backend/requirements.txt \
    && pip install -r backend/requirements-optional.txt

# ---------------------------------------------------------------- сборка

FROM base AS build

COPY backend/ ./backend/
COPY .env.example ./.env

# Датасет и модель создаются здесь же и в одном слое: промежуточный CSV
# на 25 МБ удаляется сразу, иначе он навсегда остался бы в истории слоёв
# и раздул образ.
RUN python backend/scripts/generate_dataset.py \
    && python backend/scripts/train_model.py \
    && rm -f backend/data/raw/*.csv

# ---------------------------------------------------------------- рантайм

FROM base AS runtime

# Непривилегированный пользователь: процессу приложения права root не нужны.
RUN useradd --create-home --uid 10001 shin

COPY --from=build --chown=shin:shin /app/backend /app/backend
COPY --from=build --chown=shin:shin /app/.env /app/.env

USER shin

EXPOSE 8000

# Проверяем не факт живости процесса, а готовность системы: `/health`
# вернёт degraded, если модель почему-то не загрузилась.
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/health | grep -q '"model_loaded":true' || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--app-dir", "backend"]
