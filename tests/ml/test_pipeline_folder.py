import unittest
from pathlib import Path

from app.db import repositories as repo
from app.db.connection import connect, init_db
from app.db.load_clients import load_clients

SAMPLE = Path(__file__).resolve().parent.parent / "data" / "clients_sample.csv"


def fresh():
    conn = connect(":memory:")
    init_db(conn)
    return conn


class ScriptsPipelineTests(unittest.TestCase):
    def test_process_news_folder_without_llm_classifies_and_ranks(self):
        from app.ml.ingest.bank_docs import ingest_docs
        from app.ml.pipeline import process_news_folder
        data = Path(__file__).resolve().parent.parent / "data"
        conn = fresh()
        load_clients(conn, str(SAMPLE))
        ingest_docs(conn, str(data / "bank"))
        res = process_news_folder(conn, None, str(data / "news"))
        self.assertEqual((res["created"], res["classified"]), (3, 3))
        self.assertTrue(all(n["topics"] for n in repo.list_news(conn)))
        again = process_news_folder(conn, None, str(data / "news"))
        self.assertEqual((again["created"], again["classified"]), (0, 0))


if __name__ == "__main__":
    unittest.main()
