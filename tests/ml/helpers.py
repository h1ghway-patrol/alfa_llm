from datetime import date
from pathlib import Path

from app.db.connection import connect, init_db
from app.db.documents import save_classification
from app.db.load_clients import load_clients
from app.ml.ingest.bank_docs import ingest_docs
from app.ml.ingest.news import ingest_news_folder
from app.db import repositories as repo

DATA = Path(__file__).resolve().parent.parent / "data"
TODAY = date(2026, 10, 23)


def make_env():
    conn = connect(":memory:")
    init_db(conn)
    load_clients(conn, str(DATA / "clients_sample.csv"))
    ingest_docs(conn, str(DATA / "bank"), today=TODAY)
    ingest_news_folder(conn, str(DATA / "news"))
    ids = {}
    topics = {"ЦБ снизил": (["ключевая ставка и ДКП"], 0.8), "Цены на бензин": (["нефть и топливо", "инфляция"], 0.6),
              "Курс юаня": (["курс и валюта"], 0.5)}
    for n in repo.list_news(conn):
        for prefix, (tp, imp) in topics.items():
            if n["title"].startswith(prefix):
                save_classification(conn, n["id"], tp, {"entities": [], "key_facts": [], "importance": imp})
                ids[prefix] = n["id"]
    return conn, ids
