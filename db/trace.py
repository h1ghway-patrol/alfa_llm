from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone

from app.db.repositories import save_trace_step


class StepHandle:
    def __init__(self) -> None:
        self.output = None
        self.tokens_in = 0
        self.tokens_out = 0
        self.model: str | None = None

    def set_output(self, output) -> None:
        self.output = output

    def set_tokens(self, tokens_in: int, tokens_out: int) -> None:
        self.tokens_in, self.tokens_out = tokens_in, tokens_out


class TraceRecorder:
    def __init__(self, conn: sqlite3.Connection, run_id: int) -> None:
        self.conn = conn
        self.run_id = run_id
        row = conn.execute(
            "SELECT COALESCE(MAX(step_no), 0) AS n FROM trace_step WHERE run_id = ?", (run_id,)
        ).fetchone()
        self._n = row["n"]

    @contextmanager
    def step(self, step_type: str, tool_name: str | None = None, input=None, model: str | None = None):
        handle = StepHandle()
        handle.model = model
        self._n += 1
        started = time.perf_counter()
        try:
            yield handle
        except Exception as e: 
            handle.output = {"error": f"{type(e).__name__}: {e}"}
            raise
        finally:
            save_trace_step(
                self.conn, run_id=self.run_id, step_no=self._n, step_type=step_type,
                tool_name=tool_name, input=input, output=handle.output, model=handle.model,
                tokens_in=handle.tokens_in, tokens_out=handle.tokens_out,
                latency_ms=int((time.perf_counter() - started) * 1000),
            )


def usage_by_day(
    conn: sqlite3.Connection,
    price_per_1k_in: float = 0.0,
    price_per_1k_out: float = 0.0,
    since: str | None = None,
) -> list[dict]:
    sql = ("SELECT substr(created_at,1,10) AS day, SUM(tokens_in) AS tokens_in, SUM(tokens_out) AS tokens_out"
           " FROM trace_step")
    params: list = []
    if since:
        sql += " WHERE created_at >= ?"
        params.append(since)
    sql += " GROUP BY day ORDER BY day"
    out = []
    for r in conn.execute(sql, params):
        d = dict(r)
        d["cost"] = d["tokens_in"] / 1000 * price_per_1k_in + d["tokens_out"] / 1000 * price_per_1k_out
        out.append(d)
    return out


def tokens_used_on(conn: sqlite3.Connection, day: str | None = None) -> int:
    day = day or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    row = conn.execute(
        "SELECT COALESCE(SUM(tokens_in + tokens_out), 0) AS n FROM trace_step WHERE substr(created_at,1,10) = ?",
        (day,),
    ).fetchone()
    return row["n"]


def can_spend(conn: sqlite3.Connection, n_tokens: int, daily_limit: int, day: str | None = None) -> bool:
    return tokens_used_on(conn, day) + n_tokens <= daily_limit