import tempfile
import unittest
from pathlib import Path

from app.db.connection import connect, init_db
from app.db.documents import add_document, reindex_fts
from app.db.load_clients import check_header, load_clients
from app.db.search import lemmas_text, search_chunks
from app.db import repositories as repo

SAMPLE = Path(__file__).parent / "data" / "clients_sample.csv"


def fresh():
    conn = connect(":memory:")
    init_db(conn)
    return conn


class FtsIndexesTitleAndSectionTests(unittest.TestCase):
    def setUp(self):
        self.conn = fresh()
        self.doc, _ = add_document(
            self.conn, kind="bank", title="Квантовая турбина: обзор", source_name="b", doc_date="2026-07-01",
            status="actual", chunks=[{"section_path": "Металлургический кластер", "text": "Абракадабра без ключевых слов."}])

    def test_word_only_in_title_finds_document(self):
        self.assertEqual([r["doc_id"] for r in search_chunks(self.conn, "турбина")], [self.doc])

    def test_word_only_in_section_finds_document(self):
        self.assertEqual([r["doc_id"] for r in search_chunks(self.conn, "металлургический")], [self.doc])

    def test_reindex_upgrades_old_database(self):
        with self.conn:
            self.conn.execute("UPDATE chunk SET lemmas = ?", (lemmas_text("Абракадабра без ключевых слов."),))
            self.conn.execute("INSERT INTO chunk_fts(chunk_fts) VALUES ('rebuild')")
        self.assertEqual(search_chunks(self.conn, "турбина"), [])
        self.assertEqual(reindex_fts(self.conn), 1)
        self.assertEqual(len(search_chunks(self.conn, "турбина")), 1)
        self.assertEqual(len(search_chunks(self.conn, "абракадабра")), 1)


class ClientColumnsTests(unittest.TestCase):
    def setUp(self):
        self.conn = fresh()
        load_clients(self.conn, str(SAMPLE))

    def test_bands_and_stage_are_loaded_with_api_names(self):
        c = repo.get_client(self.conn, "U_1465")
        self.assertEqual(c["employees_band"], "1000+")
        self.assertEqual(c["age_band"], "10+")
        self.assertIn("business_stage", c)
        self.assertNotIn("company_age_band", c)

    def test_key_owner_mark_is_zero_or_one(self):
        vals = {r[0] for r in self.conn.execute("SELECT key_owner_mark FROM company")}
        self.assertTrue(vals <= {0, 1, None})
        self.assertEqual(repo.get_client(self.conn, "U_1465")["key_owner_mark"], 0)
        with self.assertRaises(Exception):
            self.conn.execute("UPDATE company SET key_owner_mark = 'да' WHERE id = 'U_1465'")


class CheckHeaderTests(unittest.TestCase):
    def test_reports_missing_columns_with_suggestions(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.csv"
            p.write_text("SYNTHETIC_U;MAINOKVED_CODE;REVENUE;EXTRA\n1;2;3;4\n", encoding="utf-8")
            rep = check_header(str(p))
        self.assertIn("revenue_rub", rep["missing"])
        self.assertIn("REVENUE", rep["missing"]["revenue_rub"]["similar"])
        self.assertNotIn("id", rep["missing"])
        self.assertIn("EXTRA", rep["unmapped"])

    def test_comma_and_tab_delimiters_detected(self):
        with tempfile.TemporaryDirectory() as d:
            for delim in (",", "\t"):
                p = Path(d) / "x.csv"
                p.write_text(delim.join(["SYNTHETIC_U", "MAINOKVED_CODE", "EXTRA"]) + "\n1\t2\t3\n", encoding="utf-8")
                rep = check_header(str(p))
                self.assertEqual(rep["header"], ["SYNTHETIC_U", "MAINOKVED_CODE", "EXTRA"])
                self.assertNotIn("id", rep["missing"])

    def test_sample_header_matches_map(self):
        self.assertEqual(check_header(str(SAMPLE))["missing"], {})


if __name__ == "__main__":
    unittest.main()


class PaymentsRealHeaderTests(unittest.TestCase):
    def test_real_columns_any_order_and_delimiter(self):
        import gzip
        from app.db.load_payments import load_payments
        conn = fresh()
        load_clients(conn, str(SAMPLE))
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "pay.csv.gz"
            with gzip.open(p, "wt", encoding="utf-8") as f:
                f.write("BENEFICIARY,PAYER,PAY_AMT,PAY_CNT\nU_1465,X_9,1500.5,3\nX_8,X_7,1,1\n")
            stats = load_payments(conn, str(p))
        self.assertEqual(stats["edges_kept"], 1)
        row = conn.execute("SELECT * FROM payment").fetchone()
        self.assertEqual((row["payer"], row["beneficiary"], row["amount_rub"], row["cnt"]), ("X_9", "U_1465", 1500.5, 3))

    def test_unparsed_flag_values_are_reported_not_silent(self):
        import logging
        conn = fresh()
        with tempfile.TemporaryDirectory() as d:
            src = Path(SAMPLE).read_text(encoding="utf-8").replace(";1.0;1.0;0.0;0.0;1.0;1.0;0.0;1.0;", ";да;1.0;0.0;0.0;1.0;1.0;0.0;ЕСТЬ;", 1)
            p = Path(d) / "c.csv"
            p.write_text(src, encoding="utf-8")
            with self.assertLogs("app.db.load_clients", level="WARNING") as logs:
                stats = load_clients(conn, str(p))
        self.assertEqual(repo.get_client(conn, "U_1465")["has_loan"], 1)
        self.assertIsNone(repo.get_client(conn, "U_1465")["has_fts"])
        self.assertEqual(stats["unparsed_flags"], {"has_fts": 1})
        self.assertTrue(any("Не распознаны" in m for m in logs.output))
