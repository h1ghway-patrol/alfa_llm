"""Схемы инсайта: утверждения с источниками, шесть блоков интерпретации, запуск агента."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import ClaimKind, Status


class Claim(BaseModel):
    """Утверждение с видом и ссылками на источники."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "text": "Ключевая ставка сохранена на уровне 14% годовых",
                    "kind": "fact",
                    "source_ids": ["chunk_2026_09_11_key_rate_03"],
                },
                {
                    "text": "При прочих равных ставка 14% означает рост расходов на обслуживание кредита",
                    "kind": "ai",
                    "source_ids": [],
                },
            ]
        }
    )

    text: str = Field(description="Формулировка утверждения.")
    kind: ClaimKind = Field(
        description=(
            "Вид утверждения: `fact` — подтверждённый факт из новости, "
            "`bank` — позиция банка из его аналитики, `ai` — вывод модели, "
            "`client` — данные профиля клиента."
        )
    )
    source_ids: list[str] = Field(
        description=(
            "Идентификаторы источников, на которые опирается утверждение. "
            "У `fact` и `bank` список непустой, у `ai` может быть пустым."
        )
    )


class Consequences(BaseModel):
    """Последствия: риски и возможности раздельно."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "risks": [
                        {
                            "text": "Рост стоимости обслуживания кредита при текущей ставке",
                            "kind": "ai",
                            "source_ids": [],
                        }
                    ],
                    "opportunities": [
                        {
                            "text": "Доля плавающей ставки в портфеле позволяет пересмотреть график",
                            "kind": "ai",
                            "source_ids": [],
                        }
                    ],
                }
            ]
        }
    )

    risks: list[Claim] = Field(description="Риски для клиента.")
    opportunities: list[Claim] = Field(description="Возможности для клиента.")


class Insight(BaseModel):
    """Интерпретация события для клиента: шесть блоков и замечания по качеству данных."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "insight_id": "ins_2026_09_11_u_1465",
                    "client_id": "U_1465",
                    "event_id": "doc_2026_09_11_key_rate",
                    "status": "done",
                    "created_at": "2026-09-11T10:05:00Z",
                    "what_happened": [
                        {
                            "text": "Ключевая ставка сохранена на уровне 14% годовых",
                            "kind": "fact",
                            "source_ids": ["chunk_2026_09_11_key_rate_03"],
                        }
                    ],
                    "why_it_matters": [
                        {
                            "text": "У клиента есть кредит и лизинг, поэтому стоимость обслуживания растёт",
                            "kind": "client",
                            "source_ids": [],
                        }
                    ],
                    "consequences": {
                        "risks": [
                            {
                                "text": "Расходы на обслуживание кредита вырастут",
                                "kind": "ai",
                                "source_ids": [],
                            }
                        ],
                        "opportunities": [
                            {
                                "text": "Есть смысл пересмотреть график платежей",
                                "kind": "ai",
                                "source_ids": [],
                            }
                        ],
                    },
                    "actions": [
                        {
                            "text": "Посмотреть долю плавающей ставки в кредитном портфеле",
                            "kind": "ai",
                            "source_ids": [],
                        }
                    ],
                    "bank_view": [
                        {
                            "text": "Банк ожидает сохранения ставки до конца года",
                            "kind": "bank",
                            "source_ids": ["chunk_2026_09_07_macro_11"],
                        }
                    ],
                    "basis": [
                        {
                            "text": "Клиент — оптовая торговля, кредит и лизинг в портфеле",
                            "kind": "client",
                            "source_ids": [],
                        }
                    ],
                    "data_quality_notes": [],
                }
            ]
        }
    )

    insight_id: str = Field(description="Идентификатор инсайта.")
    client_id: str = Field(description="Клиент, для которого построена интерпретация.")
    event_id: str = Field(description="Событие, к которому относится интерпретация.")
    status: Status = Field(description="Статус интерпретации.")
    created_at: datetime = Field(description="Когда интерпретация была создана.")
    what_happened: list[Claim] = Field(description="Блок «Что произошло»: факты события со ссылками на источники.")
    why_it_matters: list[Claim] = Field(description="Блок «Почему важно именно этому клиенту».")
    consequences: Consequences = Field(description="Блок «Последствия»: риски и возможности раздельно.")
    actions: list[Claim] = Field(description="Блок «Какие действия предпринять»: конкретные шаги, не общие советы.")
    bank_view: list[Claim] = Field(description="Блок «Как это оценивает банк»: позиция Альфа-Банка с датой документа.")
    basis: list[Claim] = Field(description="Блок «На чём основан вывод»: признаки клиента и использованные источники.")
    data_quality_notes: list[str] = Field(
        description=(
            "Замечания по качеству данных: устаревшие источники, конфликт версий, пропуски. "
            "Показываются пользователю как предупреждение."
        )
    )


class Run(BaseModel):
    """Запуск генерации интерпретации: `GET /runs/{run_id}`."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "run_id": "run_7f3a91c4",
                    "status": "running",
                    "insight_id": None,
                    "error": None,
                }
            ]
        }
    )

    run_id: str = Field(description="Идентификатор запуска.")
    status: Status = Field(description="Статус запуска: `queued`, `running`, `done` или `failed`.")
    insight_id: str | None = Field(
        default=None,
        description="Идентификатор готового инсайта. Появляется, когда статус `done`.",
    )
    error: str | None = Field(default=None, description="Текст ошибки, если запуск завершился с ошибкой.")


class InsightRequest(BaseModel):
    """Тело `POST /clients/{client_id}/events/{event_id}/insight`: запуск интерпретации."""

    model_config = ConfigDict(json_schema_extra={"examples": [{}]})

    force: bool = Field(
        default=False,
        description="Пересчитать интерпретацию, даже если готовая уже есть.",
    )


class AskRequest(BaseModel):
    """Уточняющий вопрос по инсайту: `POST /clients/{client_id}/events/{event_id}/ask`."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"question": "Как изменится платёжная нагрузка при ставке 16%?"}]
        }
    )

    question: str = Field(
        min_length=1,
        max_length=500,
        description="Вопрос по инсайту или по данным в другом разрезе.",
    )


class AskResponse(BaseModel):
    """Ответ на уточняющий вопрос."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "answer": [
                        {
                            "text": "При ставке 16% расходы вырастут примерно на 2 процентных пункта",
                            "kind": "ai",
                            "source_ids": ["chunk_2026_09_07_macro_11"],
                        }
                    ],
                    "data_quality_notes": [],
                }
            ]
        }
    )

    answer: list[Claim] = Field(description="Ответ теми же утверждениями, что и в инсайте, со ссылками на источники.")
    data_quality_notes: list[str] = Field(description="Замечания по качеству данных, если они есть.")


class FeedbackRequest(BaseModel):
    """Оценка интерпретации: `POST /feedback`."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"insight_id": "ins_2026_09_11_u_1465", "rating": 5, "comment": "Полезно"}]
        }
    )

    insight_id: str = Field(description="К какой интерпретации относится оценка.")
    rating: int = Field(ge=1, le=5, description="Оценка от 1 до 5.")
    comment: str | None = Field(default=None, max_length=1000, description="Комментарий, необязателен.")


class FeedbackResponse(BaseModel):
    """Ответ `POST /feedback`: оценка принята."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"status": "accepted", "insight_id": "ins_2026_09_11_u_1465"}]
        }
    )

    status: Literal["accepted"] = Field(description="Статус: `accepted` — оценка принята в работу.")
    insight_id: str = Field(description="К какой интерпретации относится оценка.")
