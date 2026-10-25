"""Запуски интерпретации: память для фикстур и БД для рабочего режима.

В режиме фикстур запуск и инсайт живут в памяти процесса. При `USE_DB=true`
запуск, трасса и инсайт пишутся в SQLite, а текст интерпретации строит агент
из `app.ml.agent` с выбранным провайдером LLM.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from app.config import get_settings
from app.db import repositories as repo
from app.db.ids import InvalidId, parse_id
from app.db.mappers import to_insight, to_trace_step
from app.fixtures import get_client, get_event, get_sources
from app.schemas.admin import TraceStep as TraceStepOut
from app.schemas.insight import Claim, Consequences, Insight, Run
from app.schemas.source import SourceFragment
from app.store import db_mode, db_session


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
    """Запуск интерпретации в памяти или обёртка над строкой БД."""

    def __init__(self, client_id: str, event_id: str, db_id: int | None = None) -> None:
        self.run_id = f"run_{uuid.uuid4().hex[:8]}"
        self.db_id = db_id
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


def make_llm(conn):
    """Возвращает LLM-клиент согласно `LLM_PROVIDER`."""
    if get_settings().llm_provider == "remote":
        from app.ml.llm.client import LLMClient

        return LLMClient(conn)
    from app.ml.llm.fake import FakeLLM

    return FakeLLM(conn)


def create_run(client_id: str, event_id: str) -> StoredRun:
    """Создаёт запуск в статусе `queued`."""
    if db_mode():
        with db_session() as conn:
            run_id = repo.create_run(conn, client_id, parse_id(event_id))
        run = StoredRun(client_id, event_id, db_id=run_id)
        run.run_id = str(run_id)
        return run
    run = StoredRun(client_id, event_id)
    _runs[run.run_id] = run
    return run


def _run_from_row(row: dict) -> StoredRun:
    run = StoredRun(row["client_id"], str(row["doc_id"]), db_id=row["id"])
    run.run_id = str(row["id"])
    run.status = row["status"]
    run.insight_id = str(row["insight_id"]) if row.get("insight_id") is not None else None
    run.error = row["error"]
    return run


def get_run(run_id: str) -> StoredRun | None:
    """Возвращает запуск по идентификатору."""
    if db_mode():
        try:
            db_id = parse_id(run_id)
        except InvalidId:
            return None
        with db_session() as conn:
            row = repo.get_run(conn, db_id)
        return _run_from_row(row) if row is not None else None
    return _runs.get(run_id)


def _source_for_event(event_id: str) -> str | None:
    """Подбирает источник, соответствующий событию (режим фикстур)."""
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


def _complete_db_run(run: StoredRun) -> Insight:
    from app.ml.agent.run import execute_run

    with db_session() as conn:
        result = execute_run(conn, run.db_id, make_llm(conn))
        row = repo.get_run(conn, run.db_id)
        run.status = row["status"]
        run.error = row["error"]
        run.insight_id = str(row["insight_id"]) if row.get("insight_id") is not None else None
        if result is None:
            raise ValueError(run.error or "Не удалось построить интерпретацию")
        insight = repo.get_insight(conn, run.client_id, parse_id(run.event_id))
        if insight is None:
            raise ValueError("Инсайт не сохранился в БД")
        return Insight.model_validate(to_insight(insight))


def complete_run(run: StoredRun) -> Insight:
    """Выполняет запуск и возвращает готовый инсайт.

    Идемпотентно: повторный вызов в режиме фикстур возвращает тот же инсайт.
    """
    if run.db_id is not None:
        return _complete_db_run(run)

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


def trace_steps(run: StoredRun) -> list[TraceStepOut]:
    """Шаги запуска в порядке выполнения."""
    if run.db_id is not None:
        with db_session() as conn:
            rows = repo.get_trace(conn, run.db_id)
        return [TraceStepOut.model_validate(to_trace_step(row)) for row in rows]
    return [
        TraceStepOut(
            step_no=step.step_no,
            step_type=step.step_type,
            tool_name=step.tool_name,
            input=step.input,
            output=step.output,
            model=step.model,
            tokens_in=step.tokens_in,
            tokens_out=step.tokens_out,
            latency_ms=step.latency_ms,
            created_at=step.created_at,
        )
        for step in run.steps
    ]


def known_sources() -> list[SourceFragment]:
    """Источники, на которые может ссылаться заглушка."""
    return get_sources()


def usage_by_day() -> list[dict[str, object]]:
    """Расход токенов по дням: из БД или из шагов в памяти."""
    if db_mode():
        from app.db.trace import usage_by_day as db_usage

        with db_session() as conn:
            return db_usage(conn)
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
