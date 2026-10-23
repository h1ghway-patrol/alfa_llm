"""Заглушка агента и запуск интерпретации.

Держит запуск в памяти, имитирует фоновую работу и отдаёт заготовленный
инсайт. Задача B-6 заменит это на настоящего агента и запись в БД.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from app.fixtures import get_client, get_event, get_insight, get_sources
from app.schemas.insight import Claim, Consequences, Insight, Run
from app.schemas.source import SourceFragment


class TraceStep:
    """Шаг трассировки в памяти."""

    def __init__(
        self,
        step_no: int,
        step_type: str,
        tool_name: str | None,
        input_data: dict | None,
        output_data: dict | None,
        model: str | None,
        tokens_in: int,
        tokens_out: int,
        latency_ms: int,
        created_at: datetime,
    ) -> None:
        self.step_no = step_no
        self.step_type = step_type
        self.tool_name = tool_name
        self.input = input_data
        self.output = output_data
        self.model = model
        self.tokens_in = tokens_in
        self.tokens_out = tokens_out
        self.latency_ms = latency_ms
        self.created_at = created_at


class StoredRun:
    """Запуск интерпретации в памяти."""

    def __init__(self, client_id: str, event_id: str) -> None:
        self.run_id = f"run_{uuid.uuid4().hex[:8]}"
        self.client_id = client_id
        self.event_id = event_id
        self.status = "queued"
        self.insight_id: str | None = None
        self.error: str | None = None
        self.created_at = datetime.now(timezone.utc)
        self.finished_at: datetime | None = None
        self.steps: list[TraceStep] = []

    def to_schema(self) -> Run:
        return Run(
            run_id=self.run_id,
            status=self.status,  # type: ignore[arg-type]
            insight_id=self.insight_id,
            error=self.error,
        )


_runs: dict[str, StoredRun] = {}
_generated_insights: dict[tuple[str, str], Insight] = {}


def create_run(client_id: str, event_id: str) -> StoredRun:
    """Создаёт запуск в статусе `queued`."""
    run = StoredRun(client_id, event_id)
    _runs[run.run_id] = run
    return run


def get_run(run_id: str) -> StoredRun | None:
    """Возвращает запуск по идентификатору."""
    return _runs.get(run_id)


def _source_for_event(event_id: str) -> str | None:
    """Подбирает источник, соответствующий событию.

    Сначала идёт точное совпадение по заголовку документа, затем — источник
    банка по теме. Если ничего не подошло, берётся первый актуальный.
    """
    event = get_event(event_id)
    if event is None:
        return None
    sources = get_sources()
    for source in sources:
        if source.doc_title == event.title:
            return source.source_id
    for source in sources:
        if source.doc_kind == "bank" and source.freshness == "actual":
            return source.source_id
    for source in sources:
        if source.freshness == "actual":
            return source.source_id
    return sources[0].source_id if sources else None


def complete_run(run: StoredRun) -> Insight:
    """Имитирует работу агента: пишет шаги в трассу и собирает инсайт.

    Идемпотентно: повторный вызов возвращает тот же инсайт.
    """
    if run.insight_id is not None:
        existing = _generated_insights.get((run.client_id, run.event_id))
        if existing is not None:
            return existing

    run.status = "running"
    event = get_event(run.event_id)
    profile = get_client(run.client_id)
    if event is None or profile is None:
        run.status = "failed"
        run.error = "Не найдены событие или клиент"
        run.finished_at = datetime.now(timezone.utc)
        raise ValueError(run.error)

    has_loan = "loan" in profile.products
    source_id = _source_for_event(run.event_id)

    run.steps = [
        TraceStep(
            step_no=1,
            step_type="plan",
            tool_name=None,
            input_data=None,
            output_data={"plan": ["get_profile", "search_bank", "compose"]},
            model="Qwen3.6-35B-A3B",
            tokens_in=820,
            tokens_out=140,
            latency_ms=540,
            created_at=datetime.now(timezone.utc),
        ),
        TraceStep(
            step_no=2,
            step_type="tool_call",
            tool_name="search_bank",
            input_data={"query": event.title, "k": 5},
            output_data={"chunk_ids": [source_id] if source_id else []},
            model=None,
            tokens_in=1240,
            tokens_out=380,
            latency_ms=820,
            created_at=datetime.now(timezone.utc),
        ),
        TraceStep(
            step_no=3,
            step_type="model_call",
            tool_name=None,
            input_data=None,
            output_data={"blocks": 6},
            model="GLM-5.3-Flash",
            tokens_in=2100,
            tokens_out=960,
            latency_ms=1480,
            created_at=datetime.now(timezone.utc),
        ),
    ]

    debt_note = (
        "У клиента есть кредит, поэтому стоимость обслуживания растёт вместе со ставкой"
        if has_loan
        else "У клиента нет кредита, ставка влияет косвенно — через лизинг и цены на материалы"
    )

    insight = Insight(
        insight_id=f"ins_{run.run_id}",
        client_id=run.client_id,
        event_id=run.event_id,
        status="done",
        created_at=datetime.now(timezone.utc),
        what_happened=[Claim(text=event.title, kind="fact", source_ids=[source_id] if source_id else [])],
        why_it_matters=[Claim(text=debt_note, kind="client", source_ids=[])],
        consequences=Consequences(
            risks=[Claim(text="Расходы на обслуживание долга могут вырасти", kind="ai", source_ids=[])],
            opportunities=[
                Claim(text="Есть смысл пересмотреть график платежей", kind="ai", source_ids=[])
            ],
        ),
        actions=[
            Claim(
                text="Проверить долю плавающей ставки в портфеле и оценить эффект от фиксации",
                kind="ai",
                source_ids=[],
            )
        ],
        bank_view=[
            Claim(
                text="Банк ожидает сохранения текущего уровня ставки",
                kind="bank",
                source_ids=[source_id] if source_id else [],
            )
        ],
        basis=[
            Claim(
                text=f"Клиент: {profile.okved_name}, продукты: {', '.join(profile.products)}",
                kind="client",
                source_ids=[],
            )
        ],
        data_quality_notes=[],
    )

    run.status = "done"
    run.insight_id = insight.insight_id
    run.finished_at = datetime.now(timezone.utc)
    _generated_insights[(run.client_id, run.event_id)] = insight
    return insight


def get_generated_insight(client_id: str, event_id: str) -> Insight | None:
    """Инсайт, созданный заглушкой агента."""
    return _generated_insights.get((client_id, event_id))


def generated_insights() -> dict[tuple[str, str], Insight]:
    """Все инсайты, созданные заглушкой."""
    return dict(_generated_insights)


def find_insight(client_id: str, event_id: str) -> Insight | None:
    """Ищет инсайт: сначала среди созданных заглушкой, потом среди фикстур."""
    generated = get_generated_insight(client_id, event_id)
    if generated is not None:
        return generated
    return get_insight(client_id, event_id)


def trace_steps(run: StoredRun) -> list[TraceStep]:
    """Шаги запуска в порядке выполнения."""
    return list(run.steps)


def known_sources() -> list[SourceFragment]:
    """Источники, на которые может ссылаться заглушка."""
    return get_sources()


def usage_by_day() -> list[dict[str, object]]:
    """Расход токенов по дням из записанных шагов.

    Считается по трассе запусков, а не по выдуманным числам. Когда появится
    слой БД, эта же агрегация переедет в запрос к `trace_step`.
    """
    days: dict[date, dict[str, object]] = {}
    for run in _runs.values():
        for step in run.steps:
            day = step.created_at.date()
            entry = days.setdefault(
                day,
                {"date": day, "tokens_in": 0, "tokens_out": 0, "requests": 0},
            )
            entry["tokens_in"] = int(entry["tokens_in"]) + step.tokens_in
            entry["tokens_out"] = int(entry["tokens_out"]) + step.tokens_out
            if step.step_type == "model_call":
                entry["requests"] = int(entry["requests"]) + 1
    return [days[day] for day in sorted(days)]
