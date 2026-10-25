"""Роутер событий: новость без персонализации и первоисточники."""

from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies import get_current_user
from app.fixtures import get_event, get_source
from app.schemas.auth import UserOut
from app.schemas.event import Event
from app.schemas.source import SourceFragment

router = APIRouter(tags=["events"])


@router.get(
    "/events/{event_id}",
    response_model=Event,
    summary="Событие без персонализации",
    responses={
        401: {"description": "Требуется токен"},
        404: {"description": "Событие не найдено"},
    },
)
def read_event(event_id: str, user: UserOut = Depends(get_current_user)) -> Event:
    """Возвращает новость целиком: заголовок, темы, факты и текст."""
    event = get_event(event_id)
    if event is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": f"Событие {event_id} не найдено"},
        )
    return event


@router.get(
    "/sources/{source_id}",
    response_model=SourceFragment,
    summary="Первоисточник",
    responses={
        401: {"description": "Требуется токен"},
        404: {"description": "Источник не найден"},
    },
)
def read_source(source_id: str, user: UserOut = Depends(get_current_user)) -> SourceFragment:
    """Возвращает фрагмент документа, на который ссылается сноска в инсайте."""
    source = get_source(source_id)
    if source is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": f"Источник {source_id} не найден"},
        )
    return source
