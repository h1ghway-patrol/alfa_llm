from __future__ import annotations

import logging
import re
import sqlite3
from functools import lru_cache

log = logging.getLogger(__name__)

_TOKEN = re.compile(r"\w+", re.UNICODE)

try:  
    import pymorphy3

    _MORPH = pymorphy3.MorphAnalyzer()
except ImportError:  
    _MORPH = None
    log.warning("pymorphy3 не установлен: используется грубый стеммер, качество поиска ниже.")

_ENDINGS = sorted(
    ["ости", "ость", "ение", "ения", "ами", "ями", "ого", "его", "ому", "ему", "ыми", "ими",
     "ать", "ять", "ов", "ев", "ей", "ий", "ый", "ой", "ая", "яя", "ое", "ее", "ие", "ые",
     "ам", "ям", "ах", "ях", "ом", "ем", "ою", "ею", "а", "я", "ы", "и", "о", "е", "у", "ю", "ь", "й"],
    key=len, reverse=True,
)


def _crude_stem(word: str) -> str:
    for end in _ENDINGS:
        if word.endswith(end) and len(word) - len(end) >= 3:
            return word[: -len(end)]
    return word


@lru_cache(maxsize=100_000)
def _lemma(word: str) -> str:
    word = word.lower().replace("ё", "е")
    if _MORPH is not None and not word.isdigit():
        word = _MORPH.parse(word)[0].normal_form.replace("ё", "е")
        return word
    return _crude_stem(word)


def lemmatize(text: str) -> list[str]:
    return [_lemma(t) for t in _TOKEN.findall(text) if len(t) > 1 or t.isdigit()]


def lemmas_text(text: str) -> str:
    return " ".join(lemmatize(text))


def build_match_query(query: str) -> str | None:
    """Безопасный MATCH: каждая лемма в кавычках, через OR. None, если искать нечего."""
    tokens = list(dict.fromkeys(lemmatize(query)))  
    if not tokens:
        return None
    return " OR ".join('"%s"' % t.replace('"', "") for t in tokens)


def search_chunks(
    conn: sqlite3.Connection,
    query: str,
    k: int = 10,
    kind: str | None = None,
    since: str | None = None,
    include_outdated: bool = True,
) -> list[dict]:
    match = build_match_query(query)
    if match is None:
        return []
    sql = [
        "SELECT c.id AS chunk_id, c.doc_id, -bm25(chunk_fts) AS score,",
        "       c.section_path, c.text, d.title, d.doc_date, d.status, d.kind",
        "FROM chunk_fts",
        "JOIN chunk c ON c.id = chunk_fts.rowid",
        "JOIN document d ON d.id = c.doc_id",
        "WHERE chunk_fts MATCH ?",
    ]
    params: list = [match]
    if kind:
        sql.append("AND d.kind = ?")
        params.append(kind)
    if since:
        sql.append("AND d.doc_date >= ?")
        params.append(since)
    if not include_outdated:
        sql.append("AND d.status != 'outdated'")
    sql.append("ORDER BY bm25(chunk_fts) LIMIT ?")
    params.append(k)
    rows = conn.execute(" ".join(sql), params).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["fragment"] = d["text"] if len(d["text"]) <= 300 else d["text"][:300].rstrip() + "…"
        out.append(d)
    return out