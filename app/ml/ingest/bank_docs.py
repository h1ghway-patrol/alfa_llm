from __future__ import annotations

import logging
from datetime import date, datetime
from pathlib import Path

from app.db.documents import add_document
from app.ml.ingest.md_parser import parse_md, to_chunks

log = logging.getLogger(__name__)
OUTDATED_AFTER_DAYS = 540
SKIP_FILES = ("dashboard.md",)
DEFAULT_SOURCE = "Альфа-Банк (аналитика)"


def doc_status(doc_date: str | None, today: date | None = None) -> str:
    if not doc_date:
        return "unknown"
    today = today or date.today()
    age = (today - datetime.strptime(doc_date, "%Y-%m-%d").date()).days
    return "outdated" if age > OUTDATED_AFTER_DAYS else "actual"


def ingest_docs(conn, folder: str, today: date | None = None, skip: tuple[str, ...] = SKIP_FILES) -> dict:
    summary = {"documents": 0, "created": 0, "chunks": 0, "warnings": []}
    for path in sorted(Path(folder).glob("*.md")):
        if path.name in skip:
            continue
        parsed = parse_md(path.read_text(encoding="utf-8"))
        if not parsed.title:
            parsed.title = path.stem
            summary["warnings"].append(f"{path.name}: нет заголовка '# ...', взято имя файла")
        if parsed.date is None:
            summary["warnings"].append(f"{path.name}: нет даты (строка «Дата:»), doc_date=None")
        chunks = to_chunks(parsed)
        if not chunks:
            summary["warnings"].append(f"{path.name}: нет содержимого, пропущен")
            continue
        _, created = add_document(
            conn, kind="bank", title=parsed.title, chunks=chunks,
            source_name=parsed.source or DEFAULT_SOURCE, doc_date=parsed.date,
            url=parsed.url, status=doc_status(parsed.date, today))
        summary["documents"] += 1
        summary["created"] += int(created)
        summary["chunks"] += len(chunks)
    for w in summary["warnings"]:
        log.warning(w)
    log.info("Ингест банка: %s", {k: v for k, v in summary.items() if k != "warnings"})
    return summary
