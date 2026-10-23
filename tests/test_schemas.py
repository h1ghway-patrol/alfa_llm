"""Схемы: идентификаторы из БД и оценка feedback."""

from __future__ import annotations

from datetime import datetime, timezone

from app.schemas.event import FeedItem
from app.schemas.insight import FeedbackRequest


def test_numeric_id_from_db_becomes_string() -> None:
    item = FeedItem(
        event_id=42,
        title="Новость",
        published_at=datetime(2026, 9, 11, tzinfo=timezone.utc),
        source_name="Банк",
        topics=["key_rate"],
        relevance_score=0.9,
        relevance_reasons=["Тема совпадает"],
        has_insight=False,
    )
    assert item.event_id == "42"


def test_numeric_reference_ids_are_strings_too() -> None:
    request = FeedbackRequest(insight_id=7, rating=1)
    assert request.insight_id == "7"


def test_feedback_rating_is_plus_or_minus_one() -> None:
    assert FeedbackRequest(insight_id="1", rating=1).rating == 1
    assert FeedbackRequest(insight_id="1", rating=-1).rating == -1


def test_feedback_rating_rejects_five() -> None:
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        FeedbackRequest(insight_id="1", rating=5)
