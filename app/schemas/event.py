"""Схемы события: новость без персонализации и элемент ленты."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import Id, Topic


class EventFact(BaseModel):
    """Ключевой факт, извлечённый из новости."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "text": "Ключевая ставка ЦБ сохранена на уровне 14% годовых",
                    "value": 14.0,
                    "unit": "% годовых",
                    "date": "2026-09-11",
                }
            ]
        }
    )

    text: str = Field(description="Формулировка факта.")
    value: float | None = Field(default=None, description="Числовое значение, если факт содержит число.")
    unit: str | None = Field(default=None, description="Единица измерения значения, например `% годовых`.")
    date: str | None = Field(default=None, description="Дата, к которой относится факт, в формате `ГГГГ-ММ-ДД`.")


class Event(BaseModel):
    """Событие без персонализации: `GET /events/{event_id}`."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "event_id": "doc_2026_09_11_key_rate",
                    "title": "ЦБ сохранил ключевую ставку на уровне 14%",
                    "published_at": "2026-09-11T09:30:00Z",
                    "source_name": "Интерфакс",
                    "url": "https://example.com/news/key-rate-2026-09-11",
                    "topics": ["key_rate", "lending"],
                    "importance": 0.9,
                    "facts": [
                        {
                            "text": "Ключевая ставка ЦБ сохранена на уровне 14% годовых",
                            "value": 14.0,
                            "unit": "% годовых",
                            "date": "2026-09-11",
                        }
                    ],
                    "text": "Совет директоров Банка России по итогам заседания 11 сентября сохранил ключевую ставку на уровне 14% годовых.",
                }
            ]
        }
    )

    event_id: Id = Field(description="Идентификатор события (новости).")
    title: str = Field(description="Заголовок новости.")
    published_at: datetime | None = Field(
        default=None, description="Дата и время публикации. `null`, если в документе нет даты."
    )
    source_name: str | None = Field(
        default=None, description="Название источника. `null`, если источник не указан."
    )
    url: str | None = Field(default=None, description="Ссылка на оригинал, если она есть.")
    topics: list[Topic] = Field(description="Темы новости из фиксированной таксономии.")
    importance: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Важность новости по оценке классификатора, от 0 до 1.",
    )
    facts: list[EventFact] = Field(description="Ключевые факты, извлечённые из текста.")
    text: str | None = Field(default=None, description="Полный текст новости.")


class FeedItem(BaseModel):
    """Элемент ленты событий клиента: `GET /clients/{client_id}/feed`."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "event_id": "doc_2026_09_11_key_rate",
                    "title": "ЦБ сохранил ключевую ставку на уровне 14%",
                    "published_at": "2026-09-11T09:30:00Z",
                    "source_name": "Интерфакс",
                    "topics": ["key_rate", "lending"],
                    "relevance_score": 0.87,
                    "relevance_reasons": [
                        "Клиент имеет кредит: рост ставки увеличивает расходы на обслуживание",
                        "Тема новости совпадает с отраслью клиента",
                    ],
                    "has_insight": True,
                }
            ]
        }
    )

    event_id: Id = Field(description="Идентификатор события (новости).")
    title: str = Field(description="Заголовок новости.")
    published_at: datetime | None = Field(
        default=None, description="Дата и время публикации. `null`, если в документе нет даты."
    )
    source_name: str | None = Field(
        default=None, description="Название источника. `null`, если источник не указан."
    )
    topics: list[Topic] = Field(description="Темы новости из фиксированной таксономии.")
    relevance_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Оценка релевантности для этого клиента, от 0 до 1.",
    )
    relevance_reasons: list[str] = Field(
        max_length=3,
        description="До трёх причин человеческим языком: почему новость попала в ленту клиента.",
    )
    has_insight: bool = Field(description="Готова ли интерпретация для этого события.")


class FeedResponse(BaseModel):
    """Ответ `GET /clients/{client_id}/feed`."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "items": [
                        {
                            "event_id": "doc_2026_09_11_key_rate",
                            "title": "ЦБ сохранил ключевую ставку на уровне 14%",
                            "published_at": "2026-09-11T09:30:00Z",
                            "source_name": "Интерфакс",
                            "topics": ["key_rate", "lending"],
                            "relevance_score": 0.87,
                            "relevance_reasons": ["Клиент имеет кредит: ставка влияет на расходы"],
                            "has_insight": True,
                        }
                    ],
                    "total": 1,
                    "next_cursor": None,
                }
            ]
        }
    )

    items: list[FeedItem] = Field(description="События ленты, отсортированные по релевантности.")
    total: int = Field(ge=0, description="Всего найдено событий под фильтры.")
    next_cursor: str | None = Field(
        default=None,
        description="Курсор для следующей страницы. `null`, если больше нечего загружать.",
    )
