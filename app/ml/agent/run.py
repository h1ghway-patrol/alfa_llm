from __future__ import annotations

import logging
from dataclasses import dataclass

from app.db import repositories as repo
from app.db.trace import TraceRecorder
from app.ml.agent.generate import generate_insight
from app.ml.agent.planner import make_plan
from app.ml.agent.state import AgentState
from app.ml.agent.tools import run_tool
from app.ml.agent.verify import downgrade, verify_insight
from app.ml.config import load_config

log = logging.getLogger(__name__)


class AgentError(Exception):
    pass


@dataclass
class AgentResult:
    insight: dict
    sources: list[dict]


def _step(conn, recorder, state, name, args):
    try:
        with recorder.step("tool", tool_name=name, input=args) as s:
            s.set_output(run_tool(conn, state, name, args))
        return True
    except Exception as e:
        log.warning("Инструмент %s завершился ошибкой: %s", name, e)
        state.errors.append(f"{name}: {e}")
        return False


def build_sources(insight, state: AgentState) -> list[dict]:
    rows = []
    for block, idx, c in insight.iter_claims():
        key = f"{block}.{idx}"
        for cid in c.source_ids:
            rows.append({"claim_key": key, "kind": c.kind, "chunk_id": cid, "doc_id": state.source_doc(cid)})
        if c.kind == "client":
            for f in c.client_features:
                rows.append({"claim_key": key, "kind": "client", "client_feature": f})
    return rows


def run_agent(conn, client_id: str, doc_id: int, *, llm, run_id: int,
              max_steps: int | None = None, repair_rounds: int | None = None) -> AgentResult:
    cfg = load_config("agent.yaml")
    max_steps = max_steps or cfg["max_steps"]
    repair_rounds = cfg["repair_rounds"] if repair_rounds is None else repair_rounds
    recorder = TraceRecorder(conn, run_id)
    state = AgentState(client_id, doc_id)

    plan = make_plan(llm, conn, state, max_steps, recorder)
    state.plan = plan
    for step in plan[:max_steps]:
        _step(conn, recorder, state, step["tool"], step["args"])

    if state.profile is None:
        _step(conn, recorder, state, "get_profile", {})
    if not state.news_pool or not any(c["doc_id"] == doc_id for c in state.news_pool.values()):
        _step(conn, recorder, state, "get_event", {})
    if state.profile is None or state.event is None:
        raise AgentError("Не удалось получить профиль клиента или событие: " + "; ".join(state.errors))
    if not state.bank_pool:
        _step(conn, recorder, state, "retrieve_bank_context", {})

    issues: list[dict] | None = None
    for attempt in range(repair_rounds + 1):
        insight = generate_insight(llm, state, recorder, issues)
        report = verify_insight(insight, state)
        with recorder.step("check", tool_name="verify", input={"attempt": attempt}) as s:
            s.set_output(report.to_dict())
        if not report.issues:
            break
        issues = report.issues
    notes = list(report.notes)
    if report.issues:
        notes += downgrade(insight, report.issues)
    insight.data_quality_notes = list(dict.fromkeys(insight.data_quality_notes + notes))
    return AgentResult(insight.to_dict(), build_sources(insight, state))


def execute_run(conn, run_id: int, llm) -> AgentResult | None:
    run = repo.get_run(conn, run_id)
    if run is None:
        raise KeyError(f"Запуск {run_id} не найден")
    repo.update_run(conn, run_id, "running")
    try:
        result = run_agent(conn, run["client_id"], run["doc_id"], llm=llm, run_id=run_id)
        repo.save_insight(conn, run["client_id"], run["doc_id"], run_id, result.insight, result.sources)
        repo.update_run(conn, run_id, "done")
        return result
    except Exception as e:
        log.exception("Запуск %s завершился ошибкой", run_id)
        repo.update_run(conn, run_id, "failed", error=f"{type(e).__name__}: {str(e)[:400]}")
        return None
