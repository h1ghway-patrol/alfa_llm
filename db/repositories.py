from __future__ import annotations

import json
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

_ISO = "%Y-%m-%dT%H:%M:%SZ"


def _now() -> str:
    return datetime.now(timezone.utc).strftime(_ISO)


def _dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None


def list_clients(conn, *, demo_only: bool = True, limit: int = 100, search: str | None = None) -> list[dict]:
    sql = ["SELECT * FROM company WHERE 1=1"]
    params: list = []
    if demo_only:
        sql.append("AND is_demo = 1")
    else:
        sql.append("AND is_large = 1")
    if search:
        sql.append("AND (id LIKE ? OR okved_name LIKE ? OR region LIKE ? OR city LIKE ?)")
        params += [f"%{search}%"] * 4
    sql.append("ORDER BY revenue_rub DESC LIMIT ?")
    params.append(limit)
    return [dict(r) for r in conn.execute(" ".join(sql), params)]


def get_client(conn, client_id: str) -> dict | None:
    return _dict(conn.execute("SELECT * FROM company WHERE id = ?", (client_id,)).fetchone())


def get_feed(conn, client_id: str, *, topic: str | None = None, limit: int = 50,
             min_score: float = 0.0) -> list[dict]:
    sql = [
        "SELECT d.id AS event_id, d.title, d.doc_date AS published_at, d.source_name,",
        "       r.score AS relevance_score, r.reasons_json,",
        "       (SELECT group_concat(topic, ',') FROM doc_topic WHERE doc_id = d.id) AS topics,",
        "       EXISTS(SELECT 1 FROM insight i WHERE i.client_id = r.client_id",
        "              AND i.doc_id = d.id AND i.status = 'done') AS has_insight",
        "FROM relevance r JOIN document d ON d.id = r.doc_id",
        "WHERE r.client_id = ? AND d.kind = 'news' AND r.score >= ?",
    ]
    params: list = [client_id, min_score]
    if topic:
        sql.append("AND EXISTS (SELECT 1 FROM doc_topic t WHERE t.doc_id = d.id AND t.topic = ?)")
        params.append(topic)
    sql.append("ORDER BY r.score DESC, d.doc_date DESC LIMIT ?")
    params.append(limit)
    items = []
    for row in conn.execute(" ".join(sql), params):
        d = dict(row)
        d["topics"] = d["topics"].split(",") if d["topics"] else []
        d["relevance_reasons"] = json.loads(d.pop("reasons_json") or "[]")
        d["has_insight"] = bool(d["has_insight"])
        items.append(d)
    return items


def get_event(conn, doc_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM document WHERE id = ? AND kind = 'news'", (doc_id,)).fetchone()
    if row is None:
        return None
    d = dict(row)
    d["facts"] = json.loads(d.pop("facts_json")) if d.get("facts_json") else None
    d["topics"] = [r["topic"] for r in conn.execute(
        "SELECT topic FROM doc_topic WHERE doc_id = ? ORDER BY topic", (doc_id,))]
    return d


def save_relevance(conn, client_id: str, items: list[dict]) -> None:
    """Для ML-6: items = [{"doc_id", "score", "reasons": [..]}]. Заменяет оценки клиента."""
    with conn:
        conn.execute("DELETE FROM relevance WHERE client_id = ?", (client_id,))
        conn.executemany(
            "INSERT INTO relevance(client_id, doc_id, score, reasons_json) VALUES (?,?,?,?)",
            [(client_id, it["doc_id"], it["score"],
              json.dumps(it.get("reasons", []), ensure_ascii=False)) for it in items],
        )


# ---------- Запуски и инсайты ----------
def create_run(conn, client_id: str, doc_id: int) -> int:
    with conn:
        cur = conn.execute("INSERT INTO run(client_id, doc_id) VALUES (?,?)", (client_id, doc_id))
    return cur.lastrowid


def update_run(conn, run_id: int, status: str, error: str | None = None) -> None:
    finished = _now() if status in ("done", "failed") else None
    with conn:
        conn.execute(
            "UPDATE run SET status = ?, error = ?, finished_at = COALESCE(?, finished_at) WHERE id = ?",
            (status, error, finished, run_id),
        )


def get_run(conn, run_id: int) -> dict | None:
    row = conn.execute(
        "SELECT r.*, (SELECT id FROM insight i WHERE i.run_id = r.id) AS insight_id FROM run r WHERE r.id = ?",
        (run_id,),
    ).fetchone()
    return _dict(row)


def save_insight(conn, client_id: str, doc_id: int, run_id: int | None, body: dict,
                 sources: list[dict], status: str = "done") -> int:
    body_json = json.dumps(body, ensure_ascii=False)
    with conn:
        row = conn.execute(
            "SELECT id FROM insight WHERE client_id = ? AND doc_id = ?", (client_id, doc_id)
        ).fetchone()
        if row:
            insight_id = row["id"]
            conn.execute(
                "UPDATE insight SET run_id = ?, status = ?, body_json = ?, created_at = ? WHERE id = ?",
                (run_id, status, body_json, _now(), insight_id),
            )
            conn.execute("DELETE FROM insight_source WHERE insight_id = ?", (insight_id,))
        else:
            insight_id = conn.execute(
                "INSERT INTO insight(client_id, doc_id, run_id, status, body_json) VALUES (?,?,?,?,?)",
                (client_id, doc_id, run_id, status, body_json),
            ).lastrowid
        conn.executemany(
            "INSERT INTO insight_source(insight_id, claim_key, kind, chunk_id, doc_id, client_feature)"
            " VALUES (?,?,?,?,?,?)",
            [(insight_id, s["claim_key"], s["kind"], s.get("chunk_id"), s.get("doc_id"),
              s.get("client_feature")) for s in sources],
        )
    return insight_id


def get_insight(conn, client_id: str, doc_id: int) -> dict | None:
    row = conn.execute(
        "SELECT * FROM insight WHERE client_id = ? AND doc_id = ? AND status = 'done'",
        (client_id, doc_id),
    ).fetchone()
    if row is None:
        return None
    d = dict(row)
    d["body"] = json.loads(d.pop("body_json"))
    d["sources"] = [dict(r) for r in conn.execute(
        "SELECT claim_key, kind, chunk_id, doc_id, client_feature FROM insight_source"
        " WHERE insight_id = ? ORDER BY id", (d["id"],))]
    return d


def get_source(conn, chunk_id: int) -> dict | None:
    row = conn.execute(
        "SELECT c.id AS source_id, d.title AS doc_title, d.kind AS doc_kind, d.doc_date,"
        "       c.section_path, c.text, d.url, d.status AS freshness"
        " FROM chunk c JOIN document d ON d.id = c.doc_id WHERE c.id = ?",
        (chunk_id,),
    ).fetchone()
    return _dict(row)

def save_trace_step(conn, *, run_id: int, step_no: int, step_type: str, tool_name: str | None = None,
                    input=None, output=None, model: str | None = None, tokens_in: int = 0,
                    tokens_out: int = 0, latency_ms: int | None = None) -> None:
    dump = lambda v: json.dumps(v, ensure_ascii=False, default=str) if v is not None else None
    with conn:
        conn.execute(
            "INSERT INTO trace_step(run_id, step_no, step_type, tool_name, input_json, output_json,"
            " model, tokens_in, tokens_out, latency_ms) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (run_id, step_no, step_type, tool_name, dump(input), dump(output), model,
             tokens_in, tokens_out, latency_ms),
        )


def get_trace(conn, run_id: int) -> list[dict]:
    steps = []
    for r in conn.execute("SELECT * FROM trace_step WHERE run_id = ? ORDER BY step_no", (run_id,)):
        d = dict(r)
        d["input"] = json.loads(d.pop("input_json")) if d.get("input_json") else None
        d["output"] = json.loads(d.pop("output_json")) if d.get("output_json") else None
        steps.append(d)
    return steps


def create_user(conn, username: str, password_hash: str, salt: str, role: str) -> None:
    with conn:
        conn.execute(
            "INSERT INTO app_user(username, password_hash, salt, role) VALUES (?,?,?,?)"
            " ON CONFLICT(username) DO UPDATE SET password_hash=excluded.password_hash,"
            " salt=excluded.salt, role=excluded.role",
            (username, password_hash, salt, role),
        )


def get_user_by_username(conn, username: str) -> dict | None:
    return _dict(conn.execute("SELECT * FROM app_user WHERE username = ?", (username,)).fetchone())


def create_session(conn, user_id: int, ttl_seconds: int = 8 * 3600) -> str:
    token = secrets.token_urlsafe(32)
    expires = (datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)).strftime(_ISO)
    with conn:
        conn.execute("INSERT INTO session(token, user_id, expires_at) VALUES (?,?,?)",
                     (token, user_id, expires))
    return token


def get_session_user(conn, token: str) -> dict | None:
    row = conn.execute(
        "SELECT u.id, u.username, u.role FROM session s JOIN app_user u ON u.id = s.user_id"
        " WHERE s.token = ? AND s.expires_at > ?",
        (token, _now()),
    ).fetchone()
    return _dict(row)


def delete_expired_sessions(conn) -> int:
    with conn:
        return conn.execute("DELETE FROM session WHERE expires_at <= ?", (_now(),)).rowcount


def log_access(conn, user_id: int | None, client_id: str | None, action: str) -> None:
    with conn:
        conn.execute("INSERT INTO access_log(user_id, client_id, action) VALUES (?,?,?)",
                     (user_id, client_id, action))


def save_feedback(conn, insight_id: int, user_id: int, rating: int, comment: str | None = None) -> int:
    with conn:
        return conn.execute(
            "INSERT INTO feedback(insight_id, user_id, rating, comment) VALUES (?,?,?,?)",
            (insight_id, user_id, rating, comment),
        ).lastrowid