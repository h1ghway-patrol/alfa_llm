"""Согласованность фикстур: ссылки между клиентами, событиями и инсайтами."""

from __future__ import annotations

from app import fixtures


def test_demo_clients_are_loaded() -> None:
    clients = fixtures.get_clients()
    assert [client.client_id for client in clients] == ["U_1465", "U_51606", "U_57706"]
    assert all(client.is_demo for client in clients)


def test_relevance_points_to_existing_events() -> None:
    event_ids = {event.event_id for event in fixtures.get_events()}
    client_ids = {client.client_id for client in fixtures.get_clients()}
    relevance = fixtures.get_relevance()
    assert relevance, "relevance.json пуст"
    for client_id, entries in relevance.items():
        assert client_id in client_ids
        for entry in entries:
            assert entry["event_id"] in event_ids


def _all_claims(insight: fixtures.Insight):
    for field in ("what_happened", "why_it_matters", "actions", "bank_view", "basis"):
        yield from getattr(insight, field)
    yield from insight.consequences.risks
    yield from insight.consequences.opportunities


def test_insights_point_to_existing_events_clients_and_sources() -> None:
    event_ids = {event.event_id for event in fixtures.get_events()}
    client_ids = {client.client_id for client in fixtures.get_clients()}
    source_ids = {source.source_id for source in fixtures.get_sources()}
    for insight in fixtures.get_insights():
        assert insight.event_id in event_ids
        assert insight.client_id in client_ids
        for claim in _all_claims(insight):
            for source_id in claim.source_ids:
                assert source_id in source_ids, (
                    f"{insight.insight_id}: источник {source_id} отсутствует в sources.json"
                )


def test_feed_uses_only_known_events() -> None:
    for client in fixtures.get_clients():
        for item in fixtures.get_feed(client.client_id):
            assert fixtures.get_event(item.event_id) is not None
