"""Роутер админки: добавление новости, трассировка запуска, расход токенов."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from app.config import get_settings
from app.dependencies import require_role
from app.runs import get_run, trace_steps, usage_by_day
from app.schemas.admin import (
    NewsCreate,
    NewsCreateResponse,
    TraceResponse,
    TraceStep,
    UsageDay,
    UsageResponse,
)
from app.schemas.auth import UserOut

router = APIRouter(prefix="/admin", tags=["admin"])
runs_router = APIRouter(tags=["admin"])

_added_news: dict[str, NewsCreate] = {}


@router.post(
    "/news",
    response_model=NewsCreateResponse,
    summary="Добавить новость",
    status_code=status.HTTP_201_CREATED,
    responses={
        401: {"description": "Требуется токен"},
        403: {"description": "Нужна роль admin"},
        422: {"description": "Новость не прошла валидацию"},
    },
)
def create_news(
    payload: NewsCreate,
    user: UserOut = Depends(require_role("admin")),
) -> NewsCreateResponse:
    """Принимает новость и ставит её в обработку.

    Текст новости — недоверенный вход: он проверяется по длине, а содержимое
    считается данными, а не инструкциями для модели.
    """
    event_id = f"doc_{uuid.uuid4().hex[:10]}"
    _added_news[event_id] = payload
    return NewsCreateResponse(
        event_id=event_id,
        title=payload.title,
        status="queued",
        message="Новость добавлена и поставлена в обработку",
    )


@router.get(
    "/usage",
    response_model=UsageResponse,
    summary="Расход токенов по дням",
    responses={
        401: {"description": "Требуется токен"},
        403: {"description": "Нужна роль admin"},
    },
)
def usage(user: UserOut = Depends(require_role("admin"))) -> UsageResponse:
    """Расход токенов по дням из трассы запусков.

    Пока считает по шагам в памяти. Когда слоя БД хватит, источником станет
    `usage_by_day` из `app/db/trace.py`, а форма ответа не изменится.
    """
    days = [
        UsageDay(
            date=entry["date"],
            tokens_in=int(entry["tokens_in"]),
            tokens_out=int(entry["tokens_out"]),
            requests=int(entry["requests"]),
            cost_rub=None,
        )
        for entry in usage_by_day()
    ]
    settings = get_settings()
    return UsageResponse(
        days=days,
        total_tokens=sum(day.tokens_in + day.tokens_out for day in days),
        daily_limit_tokens=settings.daily_token_limit_tokens,
        budget_rub=settings.budget_rub,
    )


@runs_router.get(
    "/runs/{run_id}/trace",
    response_model=TraceResponse,
    summary="Трассировка запуска",
    responses={
        401: {"description": "Требуется токен"},
        403: {"description": "Нужна роль admin"},
        404: {"description": "Запуск не найден"},
    },
)
def run_trace(
    run_id: str,
    user: UserOut = Depends(require_role("admin")),
) -> TraceResponse:
    """Возвращает шаги агента по порядку выполнения."""
    run = get_run(run_id)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": f"Запуск {run_id} не найден"},
        )
    steps = [
        TraceStep(
            step_no=step.step_no,
            step_type=step.step_type,
            tool_name=step.tool_name,
            input=step.input,
            output=step.output,
            model=step.model,
            tokens_in=step.tokens_in,
            tokens_out=step.tokens_out,
            latency_ms=step.latency_ms,
            created_at=step.created_at,
        )
        for step in trace_steps(run)
    ]
    return TraceResponse(run_id=run.run_id, steps=steps)


