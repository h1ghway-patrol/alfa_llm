from __future__ import annotations

import sys
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi

from app.config import ConfigError, load_settings
from app.errors import register_exception_handlers
from app.logging_config import setup_logging
from app.middleware import RequestIdMiddleware
from app.routers import (
    admin_router,
    admin_runs_router,
    auth_router,
    clients_router,
    events_router,
    insights_router,
)
from app.schemas import ALL_MODELS
from app.schemas.common import HealthResponse


def build_openapi(app: FastAPI) -> dict[str, Any]:
    """Собирает OpenAPI-схему приложения.

    К схемам роутов добавляются все модели контракта из `app/schemas`, даже
    те, чьи эндпоинты ещё не подключены: фронт должен видеть полный контракт
    сразу, а не по мере появления роутеров.
    """
    if app.openapi_schema:
        return app.openapi_schema

    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    components = schema.setdefault("components", {})
    schemas = components.setdefault("schemas", {})

    for model in ALL_MODELS:
        model_schema = model.model_json_schema(ref_template="#/components/schemas/{model}")
        schemas.update(model_schema.get("$defs", {}))
        schemas[model.__name__] = {
            key: value for key, value in model_schema.items() if key != "$defs"
        }

    app.openapi_schema = schema
    return schema


def create_app() -> FastAPI:
    """Создаёт приложение с настройками из окружения."""
    settings = load_settings()
    setup_logging(settings.log_level)

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description=(
            "API персональной интерпретации новостей для клиентов банка. "
            "Все ошибки приходят в одном формате: "
            '`{"error": {"code", "message", "request_id"}}`.'
        ),
        openapi_url="/openapi.json",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    app.state.settings = settings

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=settings.cors_allow_credentials,
        allow_methods=["*"],
        allow_headers=["*", settings.request_id_header],
        expose_headers=[settings.request_id_header],
    )
    app.add_middleware(RequestIdMiddleware, header_name=settings.request_id_header)

    register_exception_handlers(app)

    app.include_router(auth_router)
    app.include_router(clients_router)
    app.include_router(events_router)
    app.include_router(insights_router)
    app.include_router(admin_router)
    app.include_router(admin_runs_router)

    @app.get("/health", response_model=HealthResponse, tags=["health"], summary="Живость сервиса")
    def health() -> HealthResponse:
        return HealthResponse(status="ok", message="app is running")

    app.openapi = lambda: build_openapi(app)  # type: ignore[method-assign]

    return app


def main() -> int:
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000, log_config=None)
    return 0


try:
    app = create_app()
except ConfigError as exc:  # pragma: no cover - зависит от окружения
    print(str(exc), file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":  # pragma: no cover
    main()
