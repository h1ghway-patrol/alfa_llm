import importlib
import unittest
from pathlib import Path

from app.db import mappers
from app.db import repositories as repo
from app.db.connection import connect, init_db
from app.db.documents import add_document
from app.db.load_clients import load_clients

SAMPLE = Path(__file__).resolve().parent.parent / "data" / "clients_sample.csv"
MODULES = ("common", "client", "event", "insight", "source", "admin")


def find_model(name):
    for mod in MODULES:
        try:
            m = importlib.import_module(f"app.schemas.{mod}")
        except Exception:
            continue
        if hasattr(m, name):
            return getattr(m, name)
    return None


def validate(model, data):
    if hasattr(model, "model_validate"):
        return model.model_validate(data)
    return model.parse_obj(data)


class MappersMatchApiSchemasTests(unittest.TestCase):
    def setUp(self):
        self.conn = connect(":memory:")
        init_db(self.conn)
        load_clients(self.conn, str(SAMPLE))
        self.doc, _ = add_document(self.conn, kind="news", title="ЦБ снизил ставку", source_name="Интерфакс",
                                   doc_date="2026-09-12", chunks=[{"text": "Ставка снижена до 14,0%."}],
                                   topics=["ключевая ставка и ДКП"])
        repo.save_relevance(self.conn, "U_1465", [{"doc_id": self.doc, "score": 0.8, "reasons": ["a"]}])

    def check(self, name, data):
        model = find_model(name)
        if model is None:
            self.skipTest(f"в app/schemas нет модели {name}")
        validate(model, data)

    def test_client_summary_and_profile_for_every_client(self):
        for row in repo.list_clients(self.conn, demo_only=False):
            self.check("ClientSummary", mappers.to_client_summary(row))
            self.check("ClientProfile", mappers.to_client_profile(row))

    def test_feed_item(self):
        self.check("FeedItem", mappers.to_feed_item(repo.get_feed(self.conn, "U_1465")[0]))

    def test_run(self):
        run_id = repo.create_run(self.conn, "U_1465", self.doc)
        self.check("Run", mappers.to_run(repo.get_run(self.conn, run_id)))

    def test_source_fragment(self):
        chunk = self.conn.execute("SELECT id FROM chunk").fetchone()[0]
        self.check("SourceFragment", mappers.to_source_fragment(repo.get_source(self.conn, chunk)))


if __name__ == "__main__":
    unittest.main()
