import logging
import tempfile
import unittest
from pathlib import Path

from app.db import repositories as repo
from app.db.build import build
from app.db.check_data import check_all, main as check_main
from app.db.connection import connect, init_db
from app.db.load_clients import load_clients
from app.db.load_counterparties import load_counterparties
from app.db.load_payments import load_payments

DATA = Path(__file__).parent / "data"


def env(counterparties=True, only_relevant=True):
    conn = connect(":memory:")
    init_db(conn)
    load_clients(conn, str(DATA / "clients_sample.csv"))
    pay = load_payments(conn, str(DATA / "payments_sample.csv"))
    stats = load_counterparties(conn, str(DATA / "counterparties_sample.csv"), only_relevant) if counterparties else None
    return conn, pay, stats


class PaymentsSampleTests(unittest.TestCase):
    def test_edges_aggregated_self_and_foreign_pairs_dropped(self):
        conn, pay, _ = env(counterparties=False)
        self.assertEqual((pay["rows_read"], pay["self_payments_skipped"], pay["edges_kept"]), (5, 1, 2))
        row = conn.execute("SELECT * FROM payment WHERE payer = 'U_1465' AND beneficiary = 'F_2'").fetchone()
        self.assertEqual((row["amount_rub"], row["cnt"]), (750.0, 4))


class LoadCounterpartiesTests(unittest.TestCase):
    def test_relevant_only_dedupe_and_empty_f(self):
        conn, _, st = env()
        self.assertEqual(st["rows_read"], 7)
        self.assertEqual(st["empty_f_skipped"], 1)
        self.assertEqual(st["filtered_out"], 2)
        self.assertEqual(st["kept"], 3)
        self.assertEqual(st["rows_without_client"], 1)
        ids = {r["f_id"] for r in conn.execute("SELECT f_id FROM counterparty")}
        self.assertEqual(ids, {"F_1", "F_2", "F_4"})

    def test_keep_all_when_filter_disabled(self):
        conn, _, st = env(only_relevant=False)
        self.assertEqual(st["kept"], 5)

    def test_idempotent_reload(self):
        conn, _, _ = env()
        load_counterparties(conn, str(DATA / "counterparties_sample.csv"))
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM counterparty").fetchone()[0], 3)

    def test_unique_pair_constraint(self):
        conn, _, _ = env()
        with self.assertRaises(Exception):
            conn.execute("INSERT INTO counterparty(f_id, client_id) VALUES ('F_1', 'U_1465')")
        with self.assertRaises(Exception):
            conn.execute("INSERT INTO counterparty(f_id, client_id) VALUES ('F_2', NULL)")

    def test_several_clients_per_f_warned(self):
        conn = connect(":memory:")
        init_db(conn)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "g.csv"
            p.write_text("SYNTHETIC_F,CITY_NAME,RC_NAME,SYNTHETIC_U\nF_1,A,B,U_1\nF_1,A,B,U_2\n", encoding="utf-8")
            with self.assertLogs("app.db.load_counterparties", level="WARNING"):
                st = load_counterparties(conn, str(p), only_relevant=False)
        self.assertEqual((st["kept"], st["f_with_several_clients"]), (2, 1))

    def test_missing_columns_message(self):
        conn = connect(":memory:")
        init_db(conn)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "g.csv"
            p.write_text("A;B\n1;2\n", encoding="utf-8")
            with self.assertRaises(ValueError) as cm:
                load_counterparties(conn, str(p))
        self.assertIn("GEO_COLUMNS", str(cm.exception))


class GraphQueriesTests(unittest.TestCase):
    def setUp(self):
        self.conn, _, _ = env()

    def test_top_counterparties_out_and_in_with_geo(self):
        out = repo.top_counterparties(self.conn, "U_1465", "out")
        self.assertEqual(out, [{"counterparty_id": "F_2", "amount_rub": 750.0, "cnt": 4,
                                "city_name": "Казань", "region_name": "Татарстан"}])
        inc = repo.top_counterparties(self.conn, "U_1465", "in")
        self.assertEqual((inc[0]["counterparty_id"], inc[0]["amount_rub"], inc[0]["city_name"]),
                         ("F_1", 1000.0, "Москва"))

    def test_client_without_payments_and_bad_direction(self):
        self.assertEqual(repo.top_counterparties(self.conn, "U_57706"), [])
        with self.assertRaises(ValueError):
            repo.top_counterparties(self.conn, "U_1465", "sideways")
        self.assertEqual(repo.top_counterparties(self.conn, "x'; DROP TABLE payment; --"), [])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM payment").fetchone()[0], 2)

    def test_counterparty_geo_lookup(self):
        geo = repo.get_counterparty_geo(self.conn, ["F_1", "F_2", "F_404"])
        self.assertEqual(geo["F_1"]["client_id"], "U_1465")
        self.assertEqual(geo["F_2"]["region_name"], "Татарстан")
        self.assertNotIn("F_404", geo)
        many = [f"X_{i}" for i in range(1200)] + ["F_4"]
        self.assertEqual(set(repo.get_counterparty_geo(self.conn, many)), {"F_4"})


class CheckDataTests(unittest.TestCase):
    def test_all_three_sample_headers_match_maps(self):
        reps = check_all(str(DATA / "clients_sample.csv"), str(DATA / "payments_sample.csv"),
                         str(DATA / "counterparties_sample.csv"))
        self.assertEqual(set(reps), {"clients", "payments", "counterparties"})
        self.assertTrue(all(not r["missing"] for r in reps.values()))
        self.assertEqual(check_main(["--payments", str(DATA / "payments_sample.csv")]), 0)

    def test_exit_code_and_suggestions_on_mismatch(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "pay.csv"
            p.write_text("BENEFICIARY;PAYER;AMOUNT;COUNT\n1;2;3;4\n", encoding="utf-8")
            rep = check_all(payments=str(p))["payments"]
            self.assertEqual(set(rep["missing"]), {"amount_rub", "cnt"})
            self.assertIn("AMOUNT", rep["missing"]["amount_rub"]["similar"])
            self.assertEqual(check_main(["--payments", str(p)]), 1)


class BuildWithThreeFilesTests(unittest.TestCase):
    def test_build_all_three_and_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            db = str(Path(d) / "app.db")
            args = dict(clients_csv=str(DATA / "clients_sample.csv"), payments_path=str(DATA / "payments_sample.csv"),
                        counterparties_path=str(DATA / "counterparties_sample.csv"))

            def counts():
                c = connect(db)
                try:
                    return tuple(c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                                 for t in ("company", "payment", "counterparty"))
                finally:
                    c.close()
            build(db, **args)
            first = counts()
            build(db, **args)
            self.assertEqual(first, counts())
            self.assertEqual(first, (5, 2, 3))
            build(db, rebuild=True, **args)
            self.assertEqual(first, counts())


if __name__ == "__main__":
    unittest.main()
