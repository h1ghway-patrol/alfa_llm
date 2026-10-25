from __future__ import annotations

from datetime import date

from app.ml.enrich.classify import classify_news
from app.ml.ingest.news import ingest_news
from app.ml.ranking.ranker import rank_all


def add_news(conn, llm, *, title: str, text: str, published_at: str | None = None,
             source_name: str | None = None, url: str | None = None,
             rerank: bool = True, today: date | None = None) -> dict:
    doc_id, created = ingest_news(conn, title=title, text=text, published_at=published_at,
                                  source_name=source_name, url=url)
    result = {"event_id": doc_id, "created": created, "topics": [], "feed_sizes": {}}
    if created:
        result["topics"] = classify_news(conn, doc_id, llm)["topics"]
        if rerank:
            result["feed_sizes"] = rank_all(conn, today=today)
    return result


def process_news_folder(conn, llm=None, folder: str | None = None, today: date | None = None) -> dict:
    from app.db import repositories as repo
    from app.ml.ingest.news import ingest_news_folder
    summary = ingest_news_folder(conn, folder) if folder else {"files": 0, "created": 0, "warnings": []}
    classified = 0
    for ev in repo.list_news(conn):
        if not (ev["topics"] and ev["facts"]):
            classify_news(conn, ev["id"], llm)
            classified += 1
    summary["classified"] = classified
    summary["feed_sizes"] = rank_all(conn, today=today)
    return summary
