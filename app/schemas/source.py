"""Схема первоисточника: фрагмент документа с метаданными и актуальностью."""

from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import DocKind, Freshness


class SourceFragment(BaseModel):
    """Первоисточник по сноске: `GET /sources/{source_id}`."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "source_id": "chunk_2026_09_11_key_rate_03",
                    "doc_title": "Ключевая ставка ЦБ (11.09.2026)",
                    "doc_kind": "news",
                    "doc_date": "2026-09-11",
                    "section_path": "Ключевая ставка",
                    "text": "Совет директоров Банка России сохранил ключевую ставку на уровне 14% годовых.",
                    "url": "https://example.com/news/key-rate-2026-09-11",
                    "freshness": "actual",
                }
            ]
        }
    )

    source_id: str = Field(description="Идентификатор фрагмента, на который ссылаются сноски в инсайте.")
    doc_title: str = Field(description="Заголовок документа-источника.")
    doc_kind: DocKind = Field(description="Тип документа: аналитика банка (`bank`) или новость (`news`).")
    doc_date: date | None = Field(
        default=None,
        description="Дата документа. `null`, если в документе нет даты, например в обзоре золота.",
    )
    section_path: str | None = Field(
        default=None,
        description="Путь по разделам документа, например `Ключевая ставка > Решение регулятора`.",
    )
    text: str = Field(description="Текст найденного фрагмента.")
    url: str | None = Field(default=None, description="Ссылка на оригинал, если она есть.")
    freshness: Freshness = Field(
        description=(
            "Актуальность источника: `actual` — актуален, `outdated` — устарел, "
            "`unknown` — определить не удалось."
        )
    )
