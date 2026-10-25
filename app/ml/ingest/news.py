from __future__ import annotations

import html
import logging
import re
from datetime import datetime
from pathlib import Path

from app.db import repositories as repo
from app.db.documents import add_document
from app.db.search import lemmatize
from app.ml.ingest.md_parser import pack_chunks, parse_date, parse_md

log = logging.getLogger(__name__)
MAX_TEXT_CHARS = 20_000
SIMILAR_TITLE_JACCARD = 0.8
_TAGS = re.compile(r"<[^>]+>")
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\u200b-\u200f\u2028\u2029\ufeff]")
_BOILER = re.compile(r"^\s*(читайте также|подписывайтесь|реклама|фото:|источник фото|поделиться)", re.I)


def clean_text(text: str) -> str:
    text = html.unescape(_TAGS.sub(" ", text or ""))
    text = _CTRL.sub("", text)
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if not _BOILER.match(ln)]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _days_apart(a: str | None, b: str | None) -> int | None:
    if not a or not b:
        return None
    f = lambda s: datetime.strptime(s[:10], "%Y-%m-%d")
    return abs((f(a) - f(b)).days)


def find_similar_news(conn, title: str, published_at: str | None, exclude_id: int | None = None) -> int | None:
    mine = set(lemmatize(title))
    if len(mine) < 3:
        return None
    for n in repo.list_news(conn):
        if n["id"] == exclude_id:
            continue
        theirs = set(lemmatize(n["title"]))
        if not theirs:
            continue
        gap = _days_apart(published_at, n["doc_date"])
        if gap is not None and gap > 3:
            continue
        if len(mine & theirs) / len(mine | theirs) >= SIMILAR_TITLE_JACCARD:
            return n["id"]
    return None


def ingest_news(conn, *, title: str, text: str, published_at: str | None = None,
                source_name: str | None = None, url: str | None = None) -> tuple[int, bool]:
    title = clean_text(title).replace("\n", " ")
    body = clean_text(text)
    if not title or not body:
        raise ValueError("У новости должны быть заголовок и текст")
    if len(body) > MAX_TEXT_CHARS:
        raise ValueError(f"Текст новости длиннее {MAX_TEXT_CHARS} символов")
    date_iso = parse_date(published_at)
    chunks = [{"section_path": None, "text": p} for p in pack_chunks(body, 1200)]
    doc_id, created = add_document(conn, kind="news", title=title, chunks=chunks, source_name=source_name,
                                   doc_date=date_iso, url=url, status="actual")
    if created and (dup := find_similar_news(conn, title, date_iso, exclude_id=doc_id)) is not None:
        with conn:
            conn.execute("DELETE FROM document WHERE id = ?", (doc_id,))
        log.info("Новость %r похожа на уже загруженную (doc %s), дубль не создан", title, dup)
        return dup, False
    return doc_id, created


def ingest_news_folder(conn, folder: str) -> dict:
    summary = {"files": 0, "created": 0, "warnings": []}
    for path in sorted(Path(folder).glob("*.md")):
        parsed = parse_md(path.read_text(encoding="utf-8"))
        text = "\n\n".join(body for _, _, body in parsed.sections)
        if not parsed.title or not text:
            summary["warnings"].append(f"{path.name}: нет заголовка или текста, пропущен")
            continue
        _, created = ingest_news(conn, title=parsed.title, text=text, published_at=parsed.date,
                                 source_name=parsed.source, url=parsed.url)
        summary["files"] += 1
        summary["created"] += int(created)
    return summary
