"""Сборка приложения: настройки приложения и схемы OpenAPI.

Схемы контракта добавляются в `/docs` и `/openapi.json` из `app/schemas`,
даже пока роутеров нет: фронт видит полный контракт сразу.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from app.schemas import ALL_MODELS
from app.schemas.common import HealthResponse


def build_openapi(app: FastAPI) -> dict[str, Any]:
    """Собирает OpenAPI-схему приложения.

    К схемам роутов добавляются все модели контракта из `app/schemas`, даже
    те, чьи эндпоинты ещё не подключены.
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
    """Создаёт приложение."""
    app = FastAPI(
        title="alfa_llm",
        version="0.1.0",
        description=(
            "API персональной интерпретации новостей для клиентов банка. "
            "Все ошибки приходят в одном формате: "
            '`{"error": {"code", "message", "request_id"}}`.'
        ),
    )

    @app.get("/health", response_model=HealthResponse, tags=["health"], summary="Живость сервиса")
    def health() -> HealthResponse:
        """Проверка живости: сервис отвечает и готов принимать запросы."""
        return HealthResponse(status="ok", message="app is running")

    app.openapi = lambda: build_openapi(app)  # type: ignore[method-assign]

    return app


app = create_app()
