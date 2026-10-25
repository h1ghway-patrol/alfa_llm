import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from app.db import mappers
from app.db import repositories as repo
from app.db.connection import connect, init_db
from app.db.documents import add_document
from app.db.ids import InvalidId, parse_id, to_str_id
from app.db.load_clients import load_clients
from app.db.search import lemmatizer_name

SAMPLE = Path(__file__).parent / "data" / "clients_sample.csv"
ROOT = Path(__file__).resolve().parent.parent


def env():
    conn = connect(":memory:")
    init_db(conn)
    load_clients(conn, str(SAMPLE))
    doc, _ = add_document(conn, kind="news", title="ЦБ снизил ставку", source_name="Интерфакс", doc_date="2026-09-12",
                          chunks=[{"text": "Ставка снижена до 14,0%."}], topics=["ключевая ставка и ДКП"],
                          facts={"importance": 0.8})
    bank, _ = add_document(conn, kind="bank", title="Макро", source_name="Банк", doc_date="2026-06-01",
                           status="actual", chunks=[{"section_path": "Ставка", "text": "Ставка 14,0%."}])
    repo.save_relevance(conn, "U_1465", [{"doc_id": doc, "score": 0.8, "reasons": ["a", "b", "c", "d"]}])
    return conn, doc, bank


class IdsTests(unittest.TestCase):
    def test_parse_valid(self):
        self.assertEqual(parse_id("42"), 42)
        self.assertEqual(parse_id(7), 7)
        self.assertEqual(parse_id("007"), 7)

    def test_parse_invalid_raises_invalid_id(self):
        for bad in ("abc", "", " 7", "7 ", "1.5", "-1", "+1", "٣", "１２", "9" * 19, None, 1.5, True, [], "1;DROP"):
            with self.assertRaises(InvalidId, msg=repr(bad)):
                parse_id(bad)
        self.assertTrue(issubclass(InvalidId, ValueError))

    def test_to_str_id(self):
        self.assertEqual(to_str_id(5), "5")
        self.assertIsNone(to_str_id(None))


class ClientMappersTests(unittest.TestCase):
    def setUp(self):
        self.conn, _, _ = env()

    def rows(self):
        return {r["id"]: r for r in repo.list_clients(self.conn, demo_only=False)}

    def test_summary_from_real_repository_row(self):
        s = mappers.to_client_summary(self.rows()["U_1465"])
        self.assertEqual(s["client_id"], "U_1465")
        self.assertNotIn("id", s)
        self.assertEqual(s["products"], ["loan", "leasing", "rko", "payroll"])
        self.assertEqual((s["employees_band"], s["age_band"], s["is_demo"]), ("1000+", "10+", True))
        self.assertEqual(s["industry"], s["okved_name"])
        json.dumps(s)

    def test_profile_flags_are_bool_or_none_and_unknown_listed(self):
        p = mappers.to_client_profile(self.rows()["U_701"])
        self.assertIsNone(p["has_loan"])
        self.assertIn("has_loan", p["unknown_features"])
        self.assertEqual(p["products"], [])
        self.assertEqual(p["fts_countries"], [])
        full = mappers.to_client_profile(
            self.rows()["U_1465"],
            tags=[{"name": "fuel_trade", "label": "Торговля топливом", "evidence": ["ОКВЭД 46.71"]}],
        )
        self.assertIs(full["has_loan"], True)
        self.assertIs(full["has_deposit"], False)
        self.assertIs(full["key_owner_mark"], False)
        self.assertEqual(full["fts_countries"], ["Китай", "Турция"])
        self.assertEqual(
            full["tags"],
            [{"code": "industry", "label": "Торговля топливом", "evidence": ["ОКВЭД 46.71"]}],
        )
        self.assertEqual(full["unknown_features"], [])
        json.dumps(full)

    def test_every_summary_field_is_in_profile(self):
        row = self.rows()["U_51606"]
        s, p = mappers.to_client_summary(row), mappers.to_client_profile(row)
        self.assertTrue(set(s) <= set(p))
        self.assertTrue(all(p[k] == s[k] for k in s))


class EventInsightMappersTests(unittest.TestCase):
    def setUp(self):
        self.conn, self.doc, self.bank = env()

    def test_feed_item(self):
        item = mappers.to_feed_item(repo.get_feed(self.conn, "U_1465")[0])
        self.assertEqual(item["event_id"], str(self.doc))
        self.assertIsInstance(item["event_id"], str)
        self.assertEqual(len(item["relevance_reasons"]), 3)
        self.assertIs(item["has_insight"], False)
        self.assertEqual(item["topics"], ["ключевая ставка и ДКП"])
        json.dumps(item)

    def test_event_and_source(self):
        ev = mappers.to_event(repo.get_event(self.conn, self.doc))
        self.assertEqual((ev["event_id"], ev["published_at"], ev["freshness"]), (str(self.doc), "2026-09-12", "unknown"))
        self.assertNotIn("content_hash", ev)
        chunk = self.conn.execute("SELECT id FROM chunk WHERE doc_id = ?", (self.bank,)).fetchone()[0]
        src = mappers.to_source_fragment(repo.get_source(self.conn, chunk))
        self.assertEqual(src["source_id"], str(chunk))
        self.assertEqual((src["doc_kind"], src["freshness"], src["section_path"]), ("bank", "actual", "Ставка"))
        self.assertEqual(parse_id(src["source_id"]), chunk)
        json.dumps([ev, src])

    def test_run_and_insight_ids_are_strings_and_roundtrip(self):
        run_id = repo.create_run(self.conn, "U_1465", self.doc)
        run = mappers.to_run(repo.get_run(self.conn, run_id))
        self.assertEqual((run["run_id"], run["status"], run["insight_id"], run["error"]), (str(run_id), "queued", None, None))
        chunk = self.conn.execute("SELECT id FROM chunk WHERE doc_id = ?", (self.doc,)).fetchone()[0]
        body = {"what_happened": [{"text": "Ставка снижена.", "kind": "fact", "source_ids": [chunk]}],
                "why_it_matters": [{"text": "Есть кредит.", "kind": "client", "source_ids": [],
                                    "client_features": ["has_loan"]}],
                "consequences": {"risks": [], "opportunities": [{"text": "Рефинанс.", "kind": "ai", "source_ids": []}]},
                "actions": [], "bank_view": [], "basis": [], "data_quality_notes": ["заметка"]}
        iid = repo.save_insight(self.conn, "U_1465", self.doc, run_id, body,
                                [{"claim_key": "what_happened.0", "kind": "fact", "chunk_id": chunk}])
        ins = mappers.to_insight(repo.get_insight(self.conn, "U_1465", self.doc))
        self.assertEqual((ins["insight_id"], ins["event_id"], ins["client_id"]), (str(iid), str(self.doc), "U_1465"))
        self.assertEqual(ins["what_happened"][0]["source_ids"], [str(chunk)])
        self.assertEqual(parse_id(ins["what_happened"][0]["source_ids"][0]), chunk)
        self.assertEqual(ins["why_it_matters"][0]["client_features"], ["has_loan"])
        self.assertEqual(ins["consequences"]["opportunities"][0]["kind"], "ai")
        self.assertEqual(ins["data_quality_notes"], ["заметка"])
        for key in ("id", "doc_id", "run_id", "body", "sources"):
            self.assertNotIn(key, ins)
        repo.update_run(self.conn, run_id, "done")
        self.assertEqual(mappers.to_run(repo.get_run(self.conn, run_id))["insight_id"], str(iid))
        json.dumps(ins)

    def test_trace_step(self):
        run_id = repo.create_run(self.conn, "U_1465", self.doc)
        repo.save_trace_step(self.conn, run_id=run_id, step_no=1, step_type="tool", tool_name="x",
                             input={"q": 1}, output={"ok": True}, tokens_in=3)
        step = mappers.to_trace_step(repo.get_trace(self.conn, run_id)[0])
        self.assertEqual((step["tool_name"], step["input"], step["tokens_in"]), ("x", {"q": 1}, 3))
        json.dumps(step)


class PymorphyRequirementTests(unittest.TestCase):
    def run_import(self, flag):
        env_ = {**os.environ, "PYTHONPATH": str(ROOT)}
        env_.pop("REQUIRE_PYMORPHY", None)
        if flag:
            env_["REQUIRE_PYMORPHY"] = "1"
        return subprocess.run([sys.executable, "-c", "import app.db.search"], env=env_, cwd=ROOT,
                              capture_output=True, text=True)

    @unittest.skipIf(lemmatizer_name() == "pymorphy3", "pymorphy3 установлен")
    def test_strict_mode_fails_loudly_without_pymorphy(self):
        r = self.run_import(True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("pymorphy3", r.stderr)
        self.assertEqual(self.run_import(False).returncode, 0)

    def test_lemmatizer_name_reports_backend(self):
        self.assertIn(lemmatizer_name(), ("pymorphy3", "crude-stemmer"))


if __name__ == "__main__":
    unittest.main()
