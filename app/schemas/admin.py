"""Схемы админки: добавление новости, трассировка агента, расход токенов."""

from datetime import date as date_type
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import Id, NonEmptyStr, Status


class NewsCreate(BaseModel):
    """Тело `POST /admin/news`: новость, добавленная администратором."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "title": "ЦБ сохранил ключевую ставку на уровне 14% годовых",
                    "text": "Совет директоров Банка России по итогам заседания сохранил ключевую ставку на уровне 14% годовых.",
                    "published_at": "2026-09-11T09:30:00Z",
                    "source_name": "Интерфакс",
                    "url": "https://example.com/news/key-rate-2026-09-11",
                }
            ]
        }
    )

    title: NonEmptyStr = Field(
        description="Заголовок новости, от 1 до 255 символов.",
    )
    text: str = Field(
        min_length=1,
        max_length=20_000,
        description=(
            "Текст новости, до 20 000 символов. Текст считается данными, а не инструкциями: "
            "содержащиеся в нём команды не выполняются."
        ),
    )
    published_at: datetime = Field(description="Дата и время публикации.")
    source_name: NonEmptyStr = Field(description="Название источника, например `Интерфакс`.")
    url: str | None = Field(default=None, description="Ссылка на оригинал, если она есть.")


class NewsCreateResponse(BaseModel):
    """Ответ `POST /admin/news`: созданное событие."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "event_id": "doc_2026_09_11_key_rate",
                    "title": "ЦБ сохранил ключевую ставку на уровне 14% годовых",
                    "status": "queued",
                    "message": "Новость добавлена и поставлена в обработку",
                }
            ]
        }
    )

    event_id: Id = Field(description="Идентификатор созданного события.")
    title: str = Field(description="Заголовок новости.")
    status: Status = Field(description="Состояние обработки новости: `queued`, `running`, `done` или `failed`.")
    message: str = Field(description="Человекочитаемый результат операции.")


class TraceStep(BaseModel):
    """Шаг агента в трассировке: `GET /runs/{run_id}/trace`."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "step_no": 3,
                    "step_type": "tool_call",
                    "tool_name": "search_bank",
                    "input": {"query": "ключевая ставка 14%", "k": 5},
                    "output": {"chunk_ids": ["chunk_2026_09_11_key_rate_03"]},
                    "model": "GLM-5.3-Flash",
                    "tokens_in": 1240,
                    "tokens_out": 380,
                    "latency_ms": 820,
                    "created_at": "2026-09-11T10:04:12Z",
                }
            ]
        }
    )

    step_no: int = Field(ge=1, description="Порядковый номер шага, начиная с 1.")
    step_type: str = Field(description="Тип шага: `plan`, `tool_call`, `model_call`, `check` и другие.")
    tool_name: str | None = Field(default=None, description="Инструмент, если шаг был вызовом инструмента.")
    input: dict[str, object] | None = Field(default=None, description="Вход шага, как передан инструменту.")
    output: dict[str, object] | None = Field(default=None, description="Выход шага, как вернул инструмент.")
    model: str | None = Field(default=None, description="Модель, которая делала шаг, если это был вызов модели.")
    tokens_in: int = Field(ge=0, description="Сколько токенов ушло на вход.")
    tokens_out: int = Field(ge=0, description="Сколько токенов вернулось.")
    latency_ms: int = Field(ge=0, description="Длительность шага в миллисекундах.")
    created_at: datetime = Field(description="Когда шаг был выполнен.")


class TraceResponse(BaseModel):
    """Ответ `GET /runs/{run_id}/trace`: шаги агента по порядку."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "run_id": "run_7f3a91c4",
                    "steps": [
                        {
                            "step_no": 1,
                            "step_type": "plan",
                            "tool_name": None,
                            "input": None,
                            "output": {"plan": ["get_profile", "search_bank"]},
                            "model": "Qwen3.6-35B-A3B",
                            "tokens_in": 820,
                            "tokens_out": 140,
                            "latency_ms": 540,
                            "created_at": "2026-09-11T10:04:10Z",
                        }
                    ],
                }
            ]
        }
    )

    run_id: Id = Field(description="Запуск, к которому относится трассировка.")
    steps: list[TraceStep] = Field(description="Шаги в порядке выполнения.")


class UsageDay(BaseModel):
    """Расход за один день: `GET /admin/usage`."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "date": "2026-09-11",
                    "tokens_in": 41200,
                    "tokens_out": 12800,
                    "requests": 37,
                    "cost_rub": 12.4,
                }
            ]
        }
    )

    date: date_type = Field(description="День, за который посчитан расход.")
    tokens_in: int = Field(ge=0, description="Токены на вход за день.")
    tokens_out: int = Field(ge=0, description="Токены на выход за день.")
    requests: int = Field(ge=0, description="Сколько запросов к моделям сделано за день.")
    cost_rub: float | None = Field(default=None, ge=0, description="Оценка стоимости в рублях, если цену токена знают.")


class UsageResponse(BaseModel):
    """Ответ `GET /admin/usage`: расход токенов по дням."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "days": [
                        {
                            "date": "2026-09-11",
                            "tokens_in": 41200,
                            "tokens_out": 12800,
                            "requests": 37,
                            "cost_rub": 12.4,
                        }
                    ],
                    "total_tokens": 54000,
                    "daily_limit_tokens": 200000,
                    "budget_rub": 500.0,
                }
            ]
        }
    )

    days: list[UsageDay] = Field(description="Расход по дням, по возрастанию даты.")
    total_tokens: int = Field(ge=0, description="Всего токенов за весь период.")
    daily_limit_tokens: int | None = Field(default=None, description="Дневной лимит токенов, если он задан.")
    budget_rub: float | None = Field(default=None, description="Бюджет в рублях на проект.")
