"""Роутер клиентов: список, профиль и лента событий."""

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import get_current_user
from app.store import get_client, get_feed, list_client_summaries
from app.schemas.auth import UserOut
from app.schemas.client import ClientProfile, ClientSummary
from app.schemas.event import FeedResponse

router = APIRouter(prefix="/clients", tags=["clients"])


@router.get(
    "",
    response_model=list[ClientSummary],
    summary="Список клиентов",
    responses={401: {"description": "Требуется токен"}},
)
def list_clients(user: UserOut = Depends(get_current_user)) -> list[ClientSummary]:
    """Возвращает демонстрационных клиентов с отраслью, регионом и продуктами."""
    return list_client_summaries()


@router.get(
    "/{client_id}/profile",
    response_model=ClientProfile,
    summary="Профиль клиента",
    responses={
        401: {"description": "Требуется токен"},
        404: {"description": "Клиент не найден"},
    },
)
def get_client_profile(
    client_id: str,
    user: UserOut = Depends(get_current_user),
) -> ClientProfile:
    """Возвращает профиль клиента с бизнес-контекстом и тегами."""
    profile = get_client(client_id)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": f"Клиент {client_id} не найден"},
        )
    return profile


@router.get(
    "/{client_id}/feed",
    response_model=FeedResponse,
    summary="Лента событий клиента",
    responses={
        401: {"description": "Требуется токен"},
        404: {"description": "Клиент не найден"},
    },
)
def get_client_feed(
    client_id: str,
    topic: str | None = Query(default=None, description="Фильтр по теме новости."),
    limit: int = Query(default=20, ge=1, le=100, description="Сколько событий вернуть."),
    user: UserOut = Depends(get_current_user),
) -> FeedResponse:
    """Возвращает ленту событий, отсортированную по релевантности для клиента."""
    if get_client(client_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": f"Клиент {client_id} не найден"},
        )
    items = get_feed(client_id, topic=topic, limit=limit)
    return FeedResponse(items=items, total=len(items), next_cursor=None)
