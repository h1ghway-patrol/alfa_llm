"""Роутер инсайтов: запуск интерпретации, её чтение, уточняющие вопросы."""

from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from fastapi.responses import JSONResponse

from app.dependencies import get_current_user
from app.runs import complete_run, create_run, get_run
from app.store import find_insight, find_insight_by_id, get_client, get_event, save_feedback
from app.schemas.auth import UserOut
from app.schemas.insight import (
    AskRequest,
    AskResponse,
    Claim,
    FeedbackRequest,
    FeedbackResponse,
    Insight,
    InsightRequest,
    Run,
)

logger = logging.getLogger("app.insights")

router = APIRouter(tags=["insights"])


@router.post(
    "/clients/{client_id}/events/{event_id}/insight",
    response_model=None,
    summary="Запустить интерпретацию",
    responses={
        200: {"model": Insight, "description": "Готовая интерпретация"},
        202: {"model": Run, "description": "Интерпретация запущена в фоне, тело — статус запуска"},
        401: {"description": "Требуется токен"},
        404: {"description": "Клиент или событие не найдено"},
    },
)
def create_insight(
    client_id: str,
    event_id: str,
    background_tasks: BackgroundTasks,
    payload: InsightRequest | None = None,
    user: UserOut = Depends(get_current_user),
):
    """Возвращает готовую интерпретацию или запускает её в фоне.

    Готовая есть — `200` с инсайтом. Готовой нет — `202` с идентификатором
    запуска, за которым нужно следить через `GET /runs/{run_id}`.
    """
    if get_client(client_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": f"Клиент {client_id} не найден"},
        )
    if get_event(event_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": f"Событие {event_id} не найдено"},
        )

    force = payload.force if payload is not None else False
    existing = None if force else find_insight(client_id, event_id)
    if existing is not None:
        return existing

    run = create_run(client_id, event_id)

    def finish() -> None:
        try:
            complete_run(run)
        except ValueError:
            pass

    if background_tasks is not None:
        background_tasks.add_task(finish)
    else:
        finish()
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content=run.to_schema().model_dump(mode="json"),
    )


@router.get(
    "/runs/{run_id}",
    response_model=Run,
    summary="Статус запуска",
    responses={
        401: {"description": "Требуется токен"},
        404: {"description": "Запуск не найден"},
    },
)
def read_run(run_id: str, user: UserOut = Depends(get_current_user)) -> Run:
    """Возвращает статус запуска интерпретации."""
    run = get_run(run_id)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": f"Запуск {run_id} не найден"},
        )
    return run.to_schema()


@router.get(
    "/clients/{client_id}/events/{event_id}/insight",
    response_model=Insight,
    summary="Готовая интерпретация",
    responses={
        401: {"description": "Требуется токен"},
        404: {"description": "Клиент, событие или интерпретация не найдены"},
    },
)
def read_insight(
    client_id: str,
    event_id: str,
    user: UserOut = Depends(get_current_user),
) -> Insight:
    """Возвращает готовую интерпретацию для пары клиент + событие."""
    if get_client(client_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": f"Клиент {client_id} не найден"},
        )
    if get_event(event_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": f"Событие {event_id} не найдено"},
        )
    insight = find_insight(client_id, event_id)
    if insight is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "not_found",
                "message": "Интерпретация ещё не готова, запустите её через POST",
            },
        )
    return insight


@router.post(
    "/clients/{client_id}/events/{event_id}/ask",
    response_model=AskResponse,
    summary="Уточняющий вопрос по инсайту",
    responses={
        401: {"description": "Требуется токен"},
        404: {"description": "Клиент или событие не найдено"},
    },
)
def ask(
    client_id: str,
    event_id: str,
    payload: AskRequest,
    user: UserOut = Depends(get_current_user),
) -> AskResponse:
    """Отвечает на уточняющий вопрос по инсайту, используя те же утверждения."""
    if get_client(client_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": f"Клиент {client_id} не найден"},
        )
    if get_event(event_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": f"Событие {event_id} не найдено"},
        )
    insight = find_insight(client_id, event_id)
    claims = list(insight.why_it_matters) if insight is not None else []
    return AskResponse(
        answer=[
            Claim(
                text=f"По вопросу «{payload.question}»: {claim.text}",
                kind=claim.kind,
                source_ids=claim.source_ids,
            )
            for claim in claims
        ],
        data_quality_notes=insight.data_quality_notes if insight is not None else [],
    )


@router.post(
    "/feedback",
    response_model=FeedbackResponse,
    summary="Оценка интерпретации",
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        401: {"description": "Требуется токен"},
        404: {"description": "Интерпретация не найдена"},
    },
)
def feedback(
    payload: FeedbackRequest,
    user: UserOut = Depends(get_current_user),
) -> FeedbackResponse:
    """Принимает и сохраняет оценку интерпретации (в БД при `USE_DB`)."""
    insight = find_insight_by_id(payload.insight_id)
    if insight is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": f"Инсайт {payload.insight_id} не найден"},
        )
    save_feedback(payload.insight_id, user.id, payload.rating, payload.comment)
    logger.info(
        "feedback_received",
        extra={
            "insight_id": payload.insight_id,
            "rating": payload.rating,
            "username": user.username,
        },
    )
    return FeedbackResponse(status="accepted", insight_id=payload.insight_id)
