"""Middleware: идентификатор запроса, заголовок `X-Request-ID`, замер времени."""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.logging_config import set_request_id

logger = logging.getLogger("app.request")

MAX_INCOMING_REQUEST_ID_LENGTH = 128


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Проставляет `request_id` в состояние запроса, логи и заголовок ответа.

    Если клиент прислал свой `X-Request-ID`, он подхватывается — так прослеживается
    цепочка запросов между сервисами. Небезопасное значение (слишком длинное или с
    управляющими символами) заменяется на новый.
    """

    def __init__(self, app, header_name: str = "X-Request-ID") -> None:
        super().__init__(app)
        self.header_name = header_name

    def _resolve_request_id(self, request: Request) -> str:
        incoming = request.headers.get(self.header_name, "")
        if incoming and len(incoming) <= MAX_INCOMING_REQUEST_ID_LENGTH and incoming.isprintable():
            return incoming
        return uuid.uuid4().hex

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = self._resolve_request_id(request)
        request.state.request_id = request_id
        set_request_id(request_id)

        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            logger.exception(
                "request_failed",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "duration_ms": duration_ms,
                },
            )
            raise
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        response.headers[self.header_name] = request_id
        logger.info(
            "request_completed",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
            },
        )
        return response
