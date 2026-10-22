"""Единый формат ошибок API и обработчики исключений.

Любая ошибка — ожидаемая (404, 401) или внезапная (500) — уходит клиенту
одним и тем же способом: `{"error": {"code", "message", "request_id"}}`.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.logging_config import get_request_id
from app.schemas.common import ErrorBody, ErrorResponse

logger = logging.getLogger("app.errors")

STATUS_TO_CODE: dict[int, str] = {
    status.HTTP_400_BAD_REQUEST: "bad_request",
    status.HTTP_401_UNAUTHORIZED: "unauthorized",
    status.HTTP_403_FORBIDDEN: "forbidden",
    status.HTTP_404_NOT_FOUND: "not_found",
    status.HTTP_405_METHOD_NOT_ALLOWED: "method_not_allowed",
    status.HTTP_409_CONFLICT: "conflict",
    status.HTTP_413_CONTENT_TOO_LARGE: "payload_too_large",
    status.HTTP_422_UNPROCESSABLE_CONTENT: "validation_error",
    status.HTTP_429_TOO_MANY_REQUESTS: "too_many_requests",
    status.HTTP_500_INTERNAL_SERVER_ERROR: "internal_error",
    status.HTTP_503_SERVICE_UNAVAILABLE: "service_unavailable",
}

DEFAULT_MESSAGE: dict[int, str] = {
    status.HTTP_400_BAD_REQUEST: "Некорректный запрос.",
    status.HTTP_401_UNAUTHORIZED: "Нужен токен: заголовок Authorization: Bearer <токен>.",
    status.HTTP_403_FORBIDDEN: "Недостаточно прав для этого запроса.",
    status.HTTP_404_NOT_FOUND: "Ресурс не найден.",
    status.HTTP_405_METHOD_NOT_ALLOWED: "Метод не поддерживается для этого адреса.",
    status.HTTP_409_CONFLICT: "Запрос конфликтует с текущим состоянием.",
    status.HTTP_413_CONTENT_TOO_LARGE: "Тело запроса слишком большое.",
    status.HTTP_422_UNPROCESSABLE_CONTENT: "Запрос не прошёл проверку полей.",
    status.HTTP_429_TOO_MANY_REQUESTS: "Слишком много запросов, попробуйте позже.",
    status.HTTP_500_INTERNAL_SERVER_ERROR: "Внутренняя ошибка сервиса. Повторите запрос позже.",
    status.HTTP_503_SERVICE_UNAVAILABLE: "Сервис временно недоступен.",
}


def error_response(
    request: Request,
    status_code: int,
    code: str | None = None,
    message: str | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """Собирает ответ с ошибкой в общем формате."""
    request_id = getattr(request.state, "request_id", None) or get_request_id() or "-"
    resolved_code = code or STATUS_TO_CODE.get(status_code, "error")
    resolved_message = message or DEFAULT_MESSAGE.get(status_code, "Ошибка запроса.")
    body = ErrorResponse(
        error=ErrorBody(
            code=resolved_code,
            message=resolved_message,
            request_id=request_id,
        )
    )
    response_headers = dict(headers or {})
    response_headers.setdefault("X-Request-ID", request_id)
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(mode="json"),
        headers=response_headers,
    )


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Ошибки, поднятые намеренно: 404, 401, 403 и прочие."""
    detail: Any = exc.detail
    if isinstance(detail, dict) and "code" in detail and "message" in detail:
        code = str(detail["code"])
        message = str(detail["message"])
    else:
        code = STATUS_TO_CODE.get(exc.status_code, "error")
        message = str(detail)
    logger.info(
        "http_error",
        extra={"status_code": exc.status_code, "error_code": code},
    )
    return error_response(
        request,
        status_code=exc.status_code,
        code=code,
        message=message,
        headers=getattr(exc, "headers", None),
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Ошибки валидации тела запроса и параметров."""
    problems = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error.get("loc", ()) if part != "body")
        problems.append(f"{location or 'тело запроса'}: {error.get('msg', 'неверное значение')}")
    message = "Проверьте поля запроса: " + "; ".join(problems[:5])
    logger.info("validation_error", extra={"problems": problems[:5]})
    return error_response(
        request,
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        code="validation_error",
        message=message,
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Всё остальное: логируем с трассировкой, клиенту отдаём обезличенный текст."""
    logger.exception("unhandled_exception", extra={"exception_type": type(exc).__name__})
    return error_response(
        request,
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        code="internal_error",
        message="Внутренняя ошибка сервиса. Повторите запрос позже.",
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Включает единый формат ошибок для приложения."""
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
