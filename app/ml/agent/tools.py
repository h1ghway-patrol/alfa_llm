from __future__ import annotations

from app.db import repositories as repo
from app.db.search import search_chunks
from app.ml.agent.state import AgentState
from app.ml.profile.builder import build_profile
from app.ml.retrieval.bank_context import retrieve_bank_context

TOOL_NAMES = ("get_profile", "get_event", "retrieve_bank_context", "search_bank", "search_news")
MAX_QUERY_CHARS = 200


class ToolError(Exception):
    pass


def _args(args: dict, need_query: bool) -> tuple[str | None, int]:
    if not isinstance(args, dict):
        raise ToolError("args должен быть объектом")
    q = args.get("query")
    if need_query:
        if not isinstance(q, str) or not q.strip():
            raise ToolError("нужен непустой query")
        q = q[:MAX_QUERY_CHARS]
    k = args.get("k", 5)
    if not isinstance(k, int) or isinstance(k, bool) or not 1 <= k <= 10:
        raise ToolError("k должно быть целым от 1 до 10")
    return q, k


def _bank_chunk(r: dict) -> dict:
    return {"chunk_id": r["chunk_id"], "doc_id": r["doc_id"], "doc_title": r["title"],
            "doc_date": r["doc_date"], "section_path": r["section_path"], "text": r["text"],
            "freshness": r["status"], "score": r["score"]}


def run_tool(conn, state: AgentState, name: str, args: dict | None = None) -> dict:
    args = args or {}
    if name not in TOOL_NAMES:
        raise ToolError(f"инструмент {name!r} не разрешён")

    if name == "get_profile":
        state.profile = build_profile(conn, state.client_id)
        return {"tags": [t.name for t in state.profile.tags]}

    if name == "get_event":
        ev = repo.get_event(conn, state.doc_id)
        if ev is None:
            raise ToolError(f"событие {state.doc_id} не найдено")
        state.event = ev
        for c in repo.get_doc_chunks(conn, state.doc_id):
            state.news_pool[c["chunk_id"]] = c
        return {"title": ev["title"], "topics": ev["topics"], "chunks": len(state.news_pool)}

    if name == "retrieve_bank_context":
        if state.event is None or state.profile is None:
            raise ToolError("сначала нужны get_event и get_profile")
        _, k = _args(args, need_query=False)
        found = retrieve_bank_context(conn, state.event, state.profile, k=max(k, 6))
        for r in found:
            state.bank_pool[r["chunk_id"]] = {**r, "status": r["freshness"], "title": r["doc_title"]}
        return {"found": [r["chunk_id"] for r in found]}

    q, k = _args(args, need_query=True)
    if name == "search_bank":
        found = search_chunks(conn, q, k=k, kind="bank")
        for r in found:
            state.bank_pool[r["chunk_id"]] = {**_bank_chunk(r), "status": r["status"], "title": r["title"]}
        return {"found": [r["chunk_id"] for r in found]}

    found = [r for r in search_chunks(conn, q, k=k + 3, kind="news") if r["doc_id"] != state.doc_id][:k]
    for r in found:
        state.news_pool[r["chunk_id"]] = {"chunk_id": r["chunk_id"], "doc_id": r["doc_id"],
                                          "title": r["title"], "doc_date": r["doc_date"],
                                          "status": r["status"], "text": r["text"]}
    return {"found": [r["chunk_id"] for r in found]}
