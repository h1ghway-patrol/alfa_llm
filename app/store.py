"""Единая точка доступа к данным API.

По умолчанию источник — JSON-фикстуры. Если включён `USE_DB`, те же функции
читают SQLite и преобразуют строки БД в схемы API через `app.db.mappers`.
Роутеры не знают, откуда пришли данные.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from app.config import get_settings
from app.db import repositories as repo
from app.db.connection import connect
from app.db.ids import InvalidId, parse_id
from app.db.mappers import (
    to_client_profile,
    to_client_summary,
    to_event,
    to_feed_item,
    to_insight,
    to_source_fragment,
)
from app.ml.profile.builder import build_profile
from app.schemas.client import (
    ClientConnections,
    ClientGeography,
    ClientProfile,
    ClientSummary,
    CounterpartyLink,
)
from app.schemas.event import Event, EventFact, FeedItem
from app.schemas.insight import Insight
from app.schemas.source import SourceFragment


def db_mode() -> bool:
    return get_settings().use_db


@contextmanager
def db_session() -> Iterator:
    conn = connect(get_settings().db_path)
    try:
        yield conn
    finally:
        conn.close()


def list_client_summaries() -> list[ClientSummary]:
    if not db_mode():
        from app.fixtures import get_client_summaries

        return get_client_summaries()
    with db_session() as conn:
        rows = repo.list_clients(conn, demo_only=True, limit=100)
        return [ClientSummary.model_validate(to_client_summary(row)) for row in rows]


def get_client(client_id: str) -> ClientProfile | None:
    if not db_mode():
        from app.fixtures import get_client as fixture_client

        return fixture_client(client_id)
    with db_session() as conn:
        row = repo.get_client(conn, client_id)
        if row is None:
            return None
        tags = [tag.to_dict() for tag in build_profile(conn, client_id).tags]
        data = to_client_profile(row, tags)
        data["payments"] = _payments(conn, client_id)
        data["connections"] = _connections(conn, client_id)
        return ClientProfile.model_validate(data)


def _payments(conn, client_id: str) -> dict[str, int]:
    row = conn.execute(
        "SELECT (SELECT COUNT(*) FROM payment WHERE beneficiary = ?) AS incoming_partners,"
        "       (SELECT COUNT(*) FROM payment WHERE payer = ?) AS outgoing_partners",
        (client_id, client_id),
    ).fetchone()
    return {"incoming_partners": row["incoming_partners"], "outgoing_partners": row["outgoing_partners"]}


def _link(row: dict) -> CounterpartyLink:
    return CounterpartyLink(
        counterparty_id=row["counterparty_id"],
        amount_rub=float(row["amount_rub"]),
        operations=int(row["cnt"]),
        city=row.get("city_name"),
        region=row.get("region_name"),
    )


def _connections(conn, client_id: str, limit: int = 5) -> ClientConnections:
    outgoing = [_link(row) for row in repo.top_counterparties(conn, client_id, "out", limit)]
    incoming = [_link(row) for row in repo.top_counterparties(conn, client_id, "in", limit)]
    geo = repo.client_counterparty_geo(conn, client_id)
    return ClientConnections(
        top_outgoing=outgoing,
        top_incoming=incoming,
        geography=ClientGeography(cities=geo["cities"], regions=geo["regions"]),
    )


def get_feed(client_id: str, topic: str | None = None, limit: int = 20) -> list[FeedItem]:
    if not db_mode():
        from app.fixtures import get_feed as fixture_feed

        return fixture_feed(client_id, topic=topic, limit=limit)
    with db_session() as conn:
        rows = repo.get_feed(conn, client_id, topic=topic, limit=limit)
        return [FeedItem.model_validate(to_feed_item(row)) for row in rows]


def get_event(event_id: str) -> Event | None:
    if not db_mode():
        from app.fixtures import get_event as fixture_event

        return fixture_event(event_id)
    try:
        doc_id = parse_id(event_id)
    except InvalidId:
        return None
    with db_session() as conn:
        row = repo.get_event(conn, doc_id)
        if row is None:
            return None
        data = to_event(row)
        facts = row.get("facts") or {}
        data["facts"] = [EventFact.model_validate(fact) for fact in facts.get("key_facts") or []]
        data["importance"] = facts.get("importance")
        data["text"] = "\n\n".join(chunk["text"] for chunk in repo.get_doc_chunks(conn, doc_id))
        return Event.model_validate(data)


def get_source(source_id: str) -> SourceFragment | None:
    if not db_mode():
        from app.fixtures import get_source as fixture_source

        return fixture_source(source_id)
    try:
        chunk_id = parse_id(source_id)
    except InvalidId:
        return None
    with db_session() as conn:
        row = repo.get_source(conn, chunk_id)
        return SourceFragment.model_validate(to_source_fragment(row)) if row is not None else None


def find_insight(client_id: str, event_id: str) -> Insight | None:
    if not db_mode():
        from app.fixtures import get_insight
        from app.runs import get_generated_insight

        return get_generated_insight(client_id, event_id) or get_insight(client_id, event_id)
    try:
        doc_id = parse_id(event_id)
    except InvalidId:
        return None
    with db_session() as conn:
        row = repo.get_insight(conn, client_id, doc_id)
        return Insight.model_validate(to_insight(row)) if row is not None else None


def find_insight_by_id(insight_id: str) -> Insight | None:
    if not db_mode():
        from app.fixtures import get_insights
        from app.runs import generated_insights

        for insight in get_insights():
            if insight.insight_id == insight_id:
                return insight
        for insight in generated_insights().values():
            if insight.insight_id == insight_id:
                return insight
        return None
    try:
        iid = parse_id(insight_id)
    except InvalidId:
        return None
    with db_session() as conn:
        row = repo.get_insight_by_id(conn, iid)
        return Insight.model_validate(to_insight(row)) if row is not None else None


def save_feedback(insight_id: str, user_id: int, rating: int, comment: str | None = None) -> None:
    if not db_mode():
        return
    with db_session() as conn:
        repo.save_feedback(conn, parse_id(insight_id), user_id, rating, comment)


__all__ = [
    "db_mode",
    "db_session",
    "find_insight",
    "find_insight_by_id",
    "get_client",
    "get_event",
    "get_feed",
    "get_source",
    "list_client_summaries",
    "save_feedback",
]
