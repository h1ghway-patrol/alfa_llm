from __future__ import annotations

import re

from app.db.search import lemmatize, search_chunks

DUP_JACCARD = 0.8
_NUM = re.compile(r"(?<!\w)\d+(?:[.,]\d+)?(?!\w)")


def build_query(event: dict, profile=None, max_tags: int = 2) -> str:
    parts = [event.get("title", "")] + list(event.get("topics", []))
    facts = (event.get("facts") or {}).get("key_facts") or []
    parts += [f["text"] for f in facts[:3]]
    if profile is not None:
        parts += [t.label for t in profile.tags[:max_tags]]
    return " ".join(p for p in parts if p)


def _numbers(text: str) -> set[str]:
    return {n.replace(",", ".") for n in _NUM.findall(text)}


def _near_duplicate(a: dict, b: dict) -> bool:
    la, lb = set(lemmatize(a["text"])), set(lemmatize(b["text"]))
    if not la or not lb or len(la & lb) / len(la | lb) < DUP_JACCARD:
        return False
    return _numbers(a["text"]) == _numbers(b["text"])


def retrieve_bank_context(conn, event: dict, profile=None, k: int = 6, query: str | None = None) -> list[dict]:
    cands = search_chunks(conn, query or build_query(event, profile), k=k * 3, kind="bank")
    for c in cands:
        c["freshness"] = c["status"]
    cands.sort(key=lambda c: (c["freshness"] == "outdated", -c["score"]))
    out: list[dict] = []
    for c in cands:
        if any(_near_duplicate(c, o) for o in out):
            continue
        out.append({"source_id": c["chunk_id"], "chunk_id": c["chunk_id"], "doc_id": c["doc_id"],
                    "doc_title": c["title"], "doc_date": c["doc_date"], "section_path": c["section_path"],
                    "text": c["text"], "score": c["score"], "freshness": c["freshness"]})
        if len(out) >= k:
            break
    return out
