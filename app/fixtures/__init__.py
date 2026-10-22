"""Заглушки на JSON-файлах.

Фикстуры лежат рядом и проходят через те же Pydantic-модели, что и настоящий
ответ API: если фикстура не соответствует контракту, приложение падает при
старте, а не отдаёт фронту невалидный JSON.

Позже эти данные заменятся репозиториями по БД (задачи B-5, B-7).
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.schemas.client import ClientProfile, ClientSummary
from app.schemas.event import Event, FeedItem
from app.schemas.insight import Insight
from app.schemas.source import SourceFragment

FIXTURES_DIR = Path(__file__).parent


def _load_json(name: str) -> Any:
    path = FIXTURES_DIR / name
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _load_models(name: str, model: type[Any]) -> list[Any]:
    raw = _load_json(name)
    if not isinstance(raw, list):
        raise ValueError(f"Фикстура {name} должна быть списком, получено {type(raw).__name__}")
    return [model.model_validate(item) for item in raw]


@lru_cache(maxsize=1)
def get_clients() -> list[ClientProfile]:
    """Все клиенты из фикстуры."""
    return _load_models("clients.json", ClientProfile)


@lru_cache(maxsize=1)
def get_client_summaries() -> list[ClientSummary]:
    """Краткие карточки клиентов для списка."""
    summaries: list[ClientSummary] = []
    for profile in get_clients():
        summaries.append(
            ClientSummary(
                client_id=profile.client_id,
                okved_code=profile.okved_code,
                okved_name=profile.okved_name,
                city=profile.city,
                region=profile.region,
                revenue_band=profile.revenue_band,
                products=profile.products,
                group_id=profile.group_id,
                group_size=profile.group_size,
                is_large=profile.is_large,
                is_demo=profile.is_demo,
            )
        )
    return summaries


@lru_cache(maxsize=1)
def get_events() -> list[Event]:
    """Все события из фикстуры."""
    return _load_models("events.json", Event)


@lru_cache(maxsize=1)
def get_insights() -> list[Insight]:
    """Готовые инсайты из фикстуры."""
    return _load_models("insights.json", Insight)


@lru_cache(maxsize=1)
def get_sources() -> list[SourceFragment]:
    """Первоисточники из фикстуры."""
    return _load_models("sources.json", SourceFragment)


@lru_cache(maxsize=1)
def get_relevance() -> dict[str, list[dict[str, Any]]]:
    """Оценки релевантности по клиентам: сырые данные из фикстуры."""
    return _load_json("relevance.json")


def get_client(client_id: str) -> ClientProfile | None:
    """Профиль клиента по идентификатору."""
    for profile in get_clients():
        if profile.client_id == client_id:
            return profile
    return None


def get_event(event_id: str) -> Event | None:
    """Событие по идентификатору."""
    for event in get_events():
        if event.event_id == event_id:
            return event
    return None


def get_insight(client_id: str, event_id: str) -> Insight | None:
    """Готовый инсайт для пары клиент + событие."""
    for insight in get_insights():
        if insight.client_id == client_id and insight.event_id == event_id:
            return insight
    return None


def get_source(source_id: str) -> SourceFragment | None:
    """Первоисточник по идентификатору."""
    for source in get_sources():
        if source.source_id == source_id:
            return source
    return None


def get_feed(client_id: str, topic: str | None = None, limit: int = 20) -> list[FeedItem]:
    """Лента событий клиента с фильтрами по теме и ограничением по количеству."""
    events_by_id = {event.event_id: event for event in get_events()}
    items: list[FeedItem] = []
    for entry in get_relevance().get(client_id, []):
        event = events_by_id.get(entry["event_id"])
        if event is None:
            continue
        if topic is not None and topic not in event.topics:
            continue
        items.append(
            FeedItem(
                event_id=event.event_id,
                title=event.title,
                published_at=event.published_at,
                source_name=event.source_name,
                topics=event.topics,
                relevance_score=entry["relevance_score"],
                relevance_reasons=entry["relevance_reasons"],
                has_insight=entry["has_insight"],
            )
        )
    items.sort(key=lambda item: (item.relevance_score, item.published_at.timestamp()), reverse=True)
    return items[:limit]
