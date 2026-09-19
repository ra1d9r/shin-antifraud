"""Точка входа FastAPI (ТЗ §2.1, §12).

Приложение собирается фабрикой `create_app()`, а не создаётся на уровне
модуля: так тесты могут поднять независимый экземпляр со своими
настройками, не полагаясь на глобальное состояние.

Модель загружается один раз в lifespan при старте — это прямое требование
ТЗ §5. Если артефакта нет, приложение всё равно поднимается: `/health`
честно сообщает `degraded`, а `/predict` возвращает 503 с инструкцией,
что запустить. Падение на старте было бы хуже — через API нельзя было бы
даже узнать причину.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.deps import build_state
from app.api.routes import analytics, health, predict, scenarios, stats, transactions
from app.config.settings import Settings, get_settings
from app.core.exceptions import ShinError
from app.core.logging import configure_logging, get_logger

logger = get_logger("shin.api")

DESCRIPTION = """
Система выявления мошеннических транзакций.

**Цепочка обработки:** транзакция → feature engineering → ML-модель →
Risk Score → Risk Engine → решение → объяснение.

| Решение | Risk Score | Что означает |
|---|---|---|
| `APPROVE` | 0–30 | транзакция проходит |
| `CHALLENGE` | 31–70 | нужна дополнительная проверка или 2FA |
| `BLOCK` | 71–100 | транзакция блокируется |

Ответ `POST /predict` содержит и `model_score` (чистый выход модели),
и `risk_score` (после политик), поэтому всегда видно, что подняло риск:
модель или бизнес-правило.

Чтобы тестировать вручную, разверните `POST /predict`, нажмите
*Try it out* и меняйте поля — результат пересчитывается на каждый запрос.
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings: Settings = app.state.settings
    configure_logging(settings.log_level)
    logger.info("Запуск %s v%s (%s)", settings.app_name, settings.app_version, settings.environment)

    app.state.shin = build_state(settings)

    if app.state.shin.model_loaded:
        logger.info("API готов принимать транзакции")
    else:
        logger.warning("API поднят без модели — /predict будет отвечать 503")

    yield

    logger.info(
        "Остановка. Обработано транзакций: %s", app.state.shin.transactions.processed_total
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    """Собрать приложение."""
    settings = settings or get_settings()

    app = FastAPI(
        title=settings.app_name,
        description=DESCRIPTION,
        version=settings.app_version,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )
    app.state.settings = settings

    # CORS для frontend (ТЗ §12).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    prefix = settings.api_prefix.rstrip("/")
    for module in (health, predict, scenarios, stats, transactions, analytics):
        app.include_router(module.router, prefix=prefix)

    _register_error_handlers(app)

    @app.get("/", include_in_schema=False)
    def root() -> dict:
        return {
            "name": settings.app_name,
            "version": settings.app_version,
            "docs": "/docs",
            "health": f"{prefix}/health",
        }

    return app


def _register_error_handlers(app: FastAPI) -> None:
    """Перевод доменных ошибок в HTTP.

    Это единственное место, где домен встречается с HTTP: сервисы и ML-слой
    бросают `ShinError` и ничего не знают про коды ответов.
    """

    @app.exception_handler(ShinError)
    async def handle_domain_error(request: Request, exc: ShinError) -> JSONResponse:
        logger.warning("%s: %s", exc.error_code, exc.message)
        return JSONResponse(status_code=exc.status_code, content=exc.to_dict())

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error_code": "validation_error",
                "message": "Некорректные данные запроса",
                "details": {"errors": _readable_validation_errors(exc)},
            },
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Непредвиденная ошибка при обработке %s", request.url.path)
        return JSONResponse(
            status_code=500,
            content={
                "error_code": "internal_error",
                "message": "Внутренняя ошибка сервера",
                "details": {},
            },
        )


def _readable_validation_errors(exc: RequestValidationError) -> list[dict]:
    """Сжать ошибки pydantic до поля и причины."""
    errors = []
    for error in exc.errors():
        location = [str(part) for part in error.get("loc", []) if part != "body"]
        errors.append({"field": ".".join(location) or "body", "message": error.get("msg", "")})
    return errors


app = create_app()
