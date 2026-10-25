from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Iterable, Sequence

from app.db.search import lemmas_text


def make_content_hash(title: str, texts: Iterable[str]) -> str:
    h = hashlib.sha256()
    h.update(title.strip().encode())
    for t in texts:
        h.update(b"\x00")
        h.update(t.strip().encode())
    return h.hexdigest()


def index_text(title: str, section_path: str | None, text: str) -> str:
    return " ".join(x for x in (title, section_path, text) if x)


def reindex_fts(conn: sqlite3.Connection) -> int:
    rows = conn.execute("SELECT c.id, c.text, c.section_path, d.title FROM chunk c"
                        " JOIN document d ON d.id = c.doc_id").fetchall()
    with conn:
        conn.executemany("UPDATE chunk SET lemmas = ? WHERE id = ?",
                         [(lemmas_text(index_text(r["title"], r["section_path"], r["text"])), r["id"])
                          for r in rows])
        conn.execute("INSERT INTO chunk_fts(chunk_fts) VALUES ('rebuild')")
    return len(rows)


def add_document(
    conn: sqlite3.Connection,
    *,
    kind: str,
    title: str,
    chunks: Sequence[dict],
    source_name: str | None = None,
    doc_date: str | None = None,
    url: str | None = None,
    status: str = "unknown",
    facts: dict | None = None,
    topics: Iterable[str] = (),
    content_hash: str | None = None,
) -> tuple[int, bool]:
    chash = content_hash or make_content_hash(title, (c["text"] for c in chunks))
    with conn:
        row = conn.execute("SELECT id FROM document WHERE content_hash = ?", (chash,)).fetchone()
        if row:
            return row["id"], False
        cur = conn.execute(
            "INSERT INTO document(kind, title, doc_date, source_name, url, status, content_hash, facts_json)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (kind, title, doc_date, source_name, url, status, chash,
             json.dumps(facts, ensure_ascii=False) if facts is not None else None),
        )
        doc_id = cur.lastrowid
        for pos, ch in enumerate(chunks):
            conn.execute(
                "INSERT INTO chunk(doc_id, section_path, position, text, lemmas) VALUES (?,?,?,?,?)",
                (doc_id, ch.get("section_path"), pos, ch["text"],
                 lemmas_text(index_text(title, ch.get("section_path"), ch["text"]))),
            )
        for t in topics:
            conn.execute("INSERT OR IGNORE INTO doc_topic(doc_id, topic) VALUES (?,?)", (doc_id, t))
    return doc_id, True


def save_classification(
    conn: sqlite3.Connection, doc_id: int, topics: Iterable[str], facts: dict | None
) -> None:
    with conn:
        conn.execute("DELETE FROM doc_topic WHERE doc_id = ?", (doc_id,))
        for t in dict.fromkeys(topics):
            conn.execute("INSERT INTO doc_topic(doc_id, topic) VALUES (?,?)", (doc_id, t))
        conn.execute(
            "UPDATE document SET facts_json = ? WHERE id = ?",
            (json.dumps(facts, ensure_ascii=False) if facts is not None else None, doc_id),
        )
