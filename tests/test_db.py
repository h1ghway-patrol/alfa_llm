import gzip
import json
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from app.db.connection import connect, init_db
from app.db import repositories as repo
from app.db.documents import add_document, save_classification
from app.db.build import build
from app.db.load_clients import load_clients
from app.db.load_payments import load_payments
from app.db.passwords import hash_password, verify_password
from app.db.search import search_chunks, build_match_query
from app.db.trace import TraceRecorder, usage_by_day, can_spend

SAMPLE = Path(__file__).parent / "data" / "clients_sample.csv"


def fresh_conn():
    conn = connect(":memory:")
    init_db(conn)
    return conn


class SchemaTests(unittest.TestCase):
    def test_schema_idempotent_and_foreign_keys_on(self):
        conn = fresh_conn()
        init_db(conn)
        self.assertEqual(conn.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO chunk(doc_id, position, text) VALUES (999, 0, 'x')")

    def test_check_constraints(self):
        conn = fresh_conn()
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO document(kind, title, content_hash) VALUES ('blog','t','h')")


class ClientsLoaderTests(unittest.TestCase):
    def setUp(self):
        self.conn = fresh_conn()
        self.stats = load_clients(self.conn, str(SAMPLE))

    def test_duplicates_removed_entirely(self):
        self.assertEqual(self.stats["duplicate_ids"], 1)
        self.assertIsNone(repo.get_client(self.conn, "U_DUP"))

    def test_only_large_loaded(self):
        ids = {r["id"] for r in self.conn.execute("SELECT id FROM company")}
        self.assertEqual(ids, {"U_1465", "U_51606", "U_57706", "U_700", "U_701"})
        self.assertEqual(self.stats["large"], 5)

    def test_group_size_counted_before_filtering(self):
        self.assertEqual(repo.get_client(self.conn, "U_1465")["group_size"], 4)
        self.assertIsNone(repo.get_client(self.conn, "U_701")["group_size"])

    def test_flags_and_nulls(self):
        c = repo.get_client(self.conn, "U_1465")
        self.assertEqual((c["has_loan"], c["has_deposit"], c["has_fts"]), (1, 0, 1))
        self.assertEqual(c["fts_countries"], "Китай,Турция")
        self.assertIsNone(c["business_stage"])
        self.assertIsNone(repo.get_client(self.conn, "U_701")["has_loan"])

    def test_demo_and_bands(self):
        demo = {c["id"] for c in repo.list_clients(self.conn, demo_only=True)}
        self.assertEqual(demo, {"U_1465", "U_51606", "U_57706"})
        self.assertTrue(all(repo.get_client(self.conn, i)["revenue_band"] for i in demo))

    def test_idempotent_reload(self):
        load_clients(self.conn, str(SAMPLE))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM company").fetchone()[0], 5)

    def test_missing_columns_message(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "bad.csv"
            p.write_text("A;B\n1;2\n", encoding="utf-8")
            with self.assertRaises(ValueError) as cm:
                load_clients(self.conn, str(p))
            self.assertIn("COLUMN_MAP", str(cm.exception))


class PaymentsTests(unittest.TestCase):
    def test_load(self):
        conn = fresh_conn()
        load_clients(conn, str(SAMPLE))
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "pay.csv.gz"
            rows = ["BENEFICIARY;PAYER;PAY_AMT;PAY_CNT",
                    "U_1465;U_1465;100;1",
                    "U_1465;X_1;100;2",
                    "U_1465;X_1;50;1",
                    "X_2;X_3;10;1"]
            with gzip.open(p, "wt", encoding="utf-8") as f:
                f.write("\n".join(rows) + "\n")
            stats = load_payments(conn, str(p))
        self.assertEqual(stats["edges_kept"], 1)
        row = conn.execute("SELECT * FROM payment").fetchone()
        self.assertEqual((row["amount_rub"], row["cnt"]), (150.0, 3))


def seed_docs(conn):
    bank, _ = add_document(
        conn, kind="bank", title="Макро 1П26", source_name="Альфа-Банк", doc_date="2026-06-01",
        status="actual",
        chunks=[{"section_path": "Ставка", "text": "Ключевая ставка Банка России снижена до 14,0%."},
                {"section_path": "Инфляция", "text": "Цены на бензин ускорили инфляцию."}])
    old, _ = add_document(
        conn, kind="bank", title="Сталь 2021", source_name="Альфа-Банк", doc_date="2021-03-01",
        status="outdated",
        chunks=[{"section_path": None, "text": "Ключевая ставка 4,25%, рынок стали растёт."}])
    news, _ = add_document(
        conn, kind="news", title="ЦБ снизил ставку", source_name="Интерфакс", doc_date="2026-09-12",
        chunks=[{"section_path": None, "text": "Банк России снизил ключевую ставку на 100 б.п."}],
        topics=["ключевая ставка"], facts={"rate": 14.0})
    return bank, old, news


class DocumentsAndSearchTests(unittest.TestCase):
    def setUp(self):
        self.conn = fresh_conn()
        self.bank, self.old, self.news = seed_docs(self.conn)

    def test_add_document_idempotent(self):
        _, created = add_document(
            self.conn, kind="news", title="ЦБ снизил ставку", source_name="x",
            chunks=[{"text": "Банк России снизил ключевую ставку на 100 б.п."}])
        self.assertFalse(created)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM document").fetchone()[0], 3)

    def test_search_finds_relevant_chunk_with_morphology(self):
        res = search_chunks(self.conn, "ключевая ставка", k=5, kind="bank", include_outdated=False)
        self.assertEqual(res[0]["doc_id"], self.bank)
        res = search_chunks(self.conn, "ставки", k=5)
        self.assertTrue(res)

    def test_search_filters(self):
        self.assertTrue(all(r["kind"] == "news" for r in search_chunks(self.conn, "ставка", kind="news")))
        res = search_chunks(self.conn, "ставка", since="2026-01-01")
        self.assertNotIn(self.old, {r["doc_id"] for r in res})
        res = search_chunks(self.conn, "ставка", include_outdated=False)
        self.assertNotIn(self.old, {r["doc_id"] for r in res})

    def test_search_survives_hostile_queries(self):
        for q in ['"', "AND OR NOT (", "ставка*", "'; DROP TABLE chunk; --", "NEAR(", "   ", "!!!"]:
            search_chunks(self.conn, q)
        self.assertEqual(search_chunks(self.conn, "!!!"), [])
        self.assertIsNone(build_match_query("   "))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM chunk").fetchone()[0], 4)

    def test_delete_document_cleans_fts(self):
        with self.conn:
            self.conn.execute("DELETE FROM document WHERE id = ?", (self.old,))
        res = search_chunks(self.conn, "сталь")
        self.assertEqual(res, [])

    def test_save_classification(self):
        save_classification(self.conn, self.news, ["инфляция", "курс"], {"x": 1})
        self.assertEqual(repo.get_event(self.conn, self.news)["topics"], ["инфляция", "курс"])


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.conn = fresh_conn()
        load_clients(self.conn, str(SAMPLE))
        self.bank, self.old, self.news = seed_docs(self.conn)
        repo.save_relevance(self.conn, "U_1465", [{"doc_id": self.news, "score": 0.9,
                                                    "reasons": ["Есть кредит", "Чувствителен к ставке"]}])

    def test_feed(self):
        feed = repo.get_feed(self.conn, "U_1465")
        self.assertEqual(len(feed), 1)
        item = feed[0]
        self.assertEqual(item["topics"], ["ключевая ставка"])
        self.assertEqual(item["relevance_reasons"], ["Есть кредит", "Чувствителен к ставке"])
        self.assertFalse(item["has_insight"])
        self.assertEqual(repo.get_feed(self.conn, "U_1465", topic="нет такой"), [])
        self.assertEqual(repo.get_feed(self.conn, "U_51606"), [])

    def test_event(self):
        ev = repo.get_event(self.conn, self.news)
        self.assertEqual(ev["facts"], {"rate": 14.0})
        self.assertIsNone(repo.get_event(self.conn, self.bank))

    def test_run_lifecycle_and_insight(self):
        run_id = repo.create_run(self.conn, "U_1465", self.news)
        self.assertEqual(repo.get_run(self.conn, run_id)["status"], "queued")
        repo.update_run(self.conn, run_id, "running")
        chunk_id = self.conn.execute("SELECT id FROM chunk LIMIT 1").fetchone()[0]
        body = {"what_happened": [{"text": "ЦБ снизил ставку", "kind": "fact", "source_ids": [chunk_id]}]}
        sources = [{"claim_key": "what_happened.0", "kind": "fact", "chunk_id": chunk_id}]
        iid = repo.save_insight(self.conn, "U_1465", self.news, run_id, body, sources)
        repo.update_run(self.conn, run_id, "done")
        run = repo.get_run(self.conn, run_id)
        self.assertEqual((run["status"], run["insight_id"]), ("done", iid))
        self.assertIsNotNone(run["finished_at"])
        self.assertTrue(repo.get_feed(self.conn, "U_1465")[0]["has_insight"])
        iid2 = repo.save_insight(self.conn, "U_1465", self.news, run_id, body, sources + sources)
        self.assertEqual(iid, iid2)
        got = repo.get_insight(self.conn, "U_1465", self.news)
        self.assertEqual(len(got["sources"]), 2)
        self.assertEqual(got["body"], body)

    def test_save_insight_is_atomic(self):
        bad = [{"claim_key": "a", "kind": "wrong-kind"}]
        with self.assertRaises(sqlite3.IntegrityError):
            repo.save_insight(self.conn, "U_1465", self.news, None, {"a": 1}, bad)
        self.assertIsNone(repo.get_insight(self.conn, "U_1465", self.news))

    def test_failed_run(self):
        run_id = repo.create_run(self.conn, "U_1465", self.news)
        repo.update_run(self.conn, run_id, "failed", error="boom")
        self.assertEqual(repo.get_run(self.conn, run_id)["error"], "boom")

    def test_source(self):
        chunk_id = self.conn.execute("SELECT id FROM chunk WHERE doc_id = ?", (self.old,)).fetchone()[0]
        src = repo.get_source(self.conn, chunk_id)
        self.assertEqual(src["freshness"], "outdated")
        self.assertEqual(src["doc_title"], "Сталь 2021")
        self.assertIsNone(repo.get_source(self.conn, 99999))

    def test_users_and_sessions(self):
        h, s = hash_password("secret")
        repo.create_user(self.conn, "u", h, s, "viewer")
        repo.create_user(self.conn, "u", h, s, "admin")
        user = repo.get_user_by_username(self.conn, "u")
        self.assertEqual(user["role"], "admin")
        self.assertTrue(verify_password("secret", user["password_hash"], user["salt"]))
        self.assertFalse(verify_password("wrong", user["password_hash"], user["salt"]))
        token = repo.create_session(self.conn, user["id"], ttl_seconds=60)
        self.assertEqual(repo.get_session_user(self.conn, token)["username"], "u")
        self.assertIsNone(repo.get_session_user(self.conn, "nope"))
        expired = repo.create_session(self.conn, user["id"], ttl_seconds=-5)
        self.assertIsNone(repo.get_session_user(self.conn, expired))
        self.assertEqual(repo.delete_expired_sessions(self.conn), 1)

    def test_sql_injection_in_search_param(self):
        self.assertEqual(repo.list_clients(self.conn, search="'; DROP TABLE company; --"), [])
        self.assertIsNotNone(repo.get_client(self.conn, "U_1465"))


class TraceTests(unittest.TestCase):
    def setUp(self):
        self.conn = fresh_conn()
        load_clients(self.conn, str(SAMPLE))
        self.news = seed_docs(self.conn)[2]
        self.run_id = repo.create_run(self.conn, "U_1465", self.news)

    def test_steps_in_order(self):
        rec = TraceRecorder(self.conn, self.run_id)
        with rec.step("plan", model="glm", input={"goal": "x"}) as s:
            s.set_output({"steps": 2})
            s.set_tokens(100, 50)
        with rec.step("tool", tool_name="search_bank", input={"q": "ставка"}) as s:
            s.set_output([1, 2])
        trace = repo.get_trace(self.conn, self.run_id)
        self.assertEqual([t["step_no"] for t in trace], [1, 2])
        self.assertEqual(trace[0]["output"], {"steps": 2})
        self.assertEqual(trace[1]["tool_name"], "search_bank")
        self.assertEqual(TraceRecorder(self.conn, self.run_id)._n, 2)

    def test_failed_step_is_recorded_and_reraised(self):
        rec = TraceRecorder(self.conn, self.run_id)
        with self.assertRaises(ValueError):
            with rec.step("tool", tool_name="broken"):
                raise ValueError("boom")
        trace = repo.get_trace(self.conn, self.run_id)
        self.assertIn("boom", trace[0]["output"]["error"])

    def test_usage_and_limit(self):
        rec = TraceRecorder(self.conn, self.run_id)
        with rec.step("llm", model="m") as s:
            s.set_tokens(1000, 500)
        usage = usage_by_day(self.conn, price_per_1k_in=0.2, price_per_1k_out=0.4)
        self.assertEqual(len(usage), 1)
        self.assertEqual((usage[0]["tokens_in"], usage[0]["tokens_out"]), (1000, 500))
        self.assertAlmostEqual(usage[0]["cost"], 0.4)
        self.assertTrue(can_spend(self.conn, 500, daily_limit=2000))
        self.assertFalse(can_spend(self.conn, 501, daily_limit=2000))


class BuildTests(unittest.TestCase):
    def test_double_build_same_counts_and_rebuild(self):
        with tempfile.TemporaryDirectory() as d:
            db = str(Path(d) / "app.db")

            def counts():
                c = connect(db)
                try:
                    return tuple(c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                                 for t in ("company", "app_user"))
                finally:
                    c.close()

            build(db, clients_csv=str(SAMPLE))
            first = counts()
            build(db, clients_csv=str(SAMPLE))
            self.assertEqual(first, counts())
            self.assertEqual(first, (5, 2))
            build(db, clients_csv=str(SAMPLE), rebuild=True)
            self.assertEqual(first, counts())
            c = connect(db)
            self.assertEqual(c.execute("PRAGMA journal_mode").fetchone()[0], "wal")
            c.close()

    def test_all_clients_flag(self):
        with tempfile.TemporaryDirectory() as d:
            db = str(Path(d) / "app.db")
            build(db, clients_csv=str(SAMPLE), all_clients=True)
            c = connect(db)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM company").fetchone()[0], 6)
            c.close()


if __name__ == "__main__":
    unittest.main()
