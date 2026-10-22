"""Общие схемы API: перечисления, страница результатов, тело ошибки.

Используются всеми остальными модулями `app/schemas`. Идентификаторы сущностей
в именах полей: у самой сущности поле называется `id`, а в других сущностях
ссылка на неё — с уточнением (`client_id`, `event_id`, `source_id`).
"""

from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field


def _strip_whitespace(value: object) -> object:
    """Убирает пробелы по краям строки, остальные типы не трогает."""
    if isinstance(value, str):
        return value.strip()
    return value


NonEmptyStr = Annotated[
    str,
    BeforeValidator(_strip_whitespace),
    Field(min_length=1, max_length=255),
]
"""Строка без пробелов по краям и непустая. Пустая строка после обрезки — ошибка валидации."""


DocKind = Literal["bank", "news"]
"""Тип документа: аналитика банка (`bank`) или внешняя новость (`news`)."""

ClaimKind = Literal["fact", "bank", "ai", "client"]
"""Вид утверждения в инсайте: факт из новости, позиция банка, вывод AI, данные клиента."""

Status = Literal["queued", "running", "done", "failed"]
"""Статус задания: в очереди, выполняется, готово, ошибка."""

Freshness = Literal["actual", "outdated", "unknown"]
"""Актуальность источника: актуален, устарел, актуальность неизвестна."""

Topic = Annotated[
    str,
    Field(
        description=(
            "Тема новости из фиксированной таксономии (ML-4): ключевая ставка и ДКП, "
            "инфляция, курс и валюта, бюджет и ОФЗ, потребление, рынок труда, "
            "нефть и топливо, золото и сырьё, кредитование, геополитика, "
            "регулирование, отраслевые события."
        )
    ),
]


class ErrorBody(BaseModel):
    """Тело ошибки: машиночитаемый код, текст для человека и идентификатор запроса."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "code": "not_found",
                    "message": "Клиент U_999999 не найден",
                    "request_id": "8f1c4a2e-6d1b-4f5a-9c33-1f0a2b7d5e11",
                }
            ]
        }
    )

    code: str = Field(
        description="Машиночитаемый код ошибки, snake_case: `not_found`, `forbidden`, `validation_error`, `internal_error`.",
        examples=["not_found"],
    )
    message: str = Field(
        description="Текст ошибки для пользователя, по-русски.",
        examples=["Клиент U_999999 не найден"],
    )
    request_id: str = Field(
        description="Идентификатор запроса: дублируется в заголовке `X-Request-ID` и в логах.",
        examples=["8f1c4a2e-6d1b-4f5a-9c33-1f0a2b7d5e11"],
    )


class ErrorResponse(BaseModel):
    """Единый формат ответа с ошибкой для всех эндпоинтов."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "error": {
                        "code": "not_found",
                        "message": "Клиент U_999999 не найден",
                        "request_id": "8f1c4a2e-6d1b-4f5a-9c33-1f0a2b7d5e11",
                    }
                }
            ]
        }
    )

    error: ErrorBody = Field(description="Описание ошибки.")


class HealthResponse(BaseModel):
    """Ответ `GET /health`: сервис жив."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"status": "ok", "message": "app is running"}]
        }
    )

    status: Literal["ok"] = Field(description="Статус сервиса. Пока всегда `ok`.")
    message: str = Field(
        description="Человекочитаемый текст о состоянии.",
        examples=["app is running"],
    )
