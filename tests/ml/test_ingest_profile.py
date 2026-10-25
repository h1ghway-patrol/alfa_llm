import tempfile
import unittest
from pathlib import Path

from app.db import repositories as repo
from app.db.connection import connect, init_db
from app.db.load_clients import load_clients
from app.ml.ingest.bank_docs import ingest_docs
from app.ml.ingest.md_parser import parse_date, parse_md, to_chunks
from app.ml.ingest.news import clean_text, ingest_news, ingest_news_folder
from app.ml.profile.builder import build_profile, match_okved
from tests.ml.helpers import DATA, TODAY, make_env


class MdParserTests(unittest.TestCase):
    def test_parse_date_formats(self):
        self.assertEqual(parse_date("05.08.2026"), "2026-08-05")
        self.assertEqual(parse_date("5 августа 2026"), "2026-08-05")
        self.assertEqual(parse_date("2026-08-05"), "2026-08-05")
        self.assertIsNone(parse_date("скоро"))
        self.assertIsNone(parse_date("31.02.2026"))

    def test_table_stays_whole_and_heading_in_text(self):
        doc = parse_md((DATA / "bank" / "macro_1h26.md").read_text(encoding="utf-8"))
        chunks = to_chunks(doc)
        table = [c for c in chunks if "|---|---|" in c["text"]]
        self.assertEqual(len(table), 1)
        self.assertIn("| Бензин, м/м | 3,1% |", table[0]["text"])
        self.assertTrue(table[0]["text"].startswith("Инфляция"))
        self.assertEqual(table[0]["section_path"], "Инфляция")
        self.assertTrue(all(c["text"].strip() for c in chunks))

    def test_meta_lines_not_in_body(self):
        doc = parse_md((DATA / "bank" / "macro_1h26.md").read_text(encoding="utf-8"))
        self.assertEqual((doc.date, doc.source), ("2026-06-01", "Альфа-Банк, Макроэкономика"))
        self.assertNotIn("Дата:", " ".join(t for _, _, t in doc.sections))


class BankIngestTests(unittest.TestCase):
    def setUp(self):
        self.conn = connect(":memory:")
        init_db(self.conn)
        self.summary = ingest_docs(self.conn, str(DATA / "bank"), today=TODAY)

    def doc(self, title_part):
        return self.conn.execute("SELECT * FROM document WHERE title LIKE ?", (f"%{title_part}%",)).fetchone()

    def test_summary_and_skip_dashboard(self):
        self.assertEqual(self.summary["documents"], 5)
        self.assertIsNone(self.doc("Сводка"))

    def test_date_from_line_not_filename(self):
        self.assertEqual(self.doc("Потребление")["doc_date"], "2026-08-05")

    def test_missing_date_and_outdated(self):
        gold = self.doc("Золото")
        self.assertIsNone(gold["doc_date"])
        self.assertEqual(gold["status"], "unknown")
        self.assertTrue(any("gold.md" in w for w in self.summary["warnings"]))
        self.assertEqual(self.doc("стали")["status"], "outdated")
        self.assertEqual(self.doc("Макро")["status"], "actual")

    def test_idempotent_and_no_empty_chunks(self):
        before = self.conn.execute("SELECT COUNT(*) FROM chunk").fetchone()[0]
        again = ingest_docs(self.conn, str(DATA / "bank"), today=TODAY)
        self.assertEqual(again["created"], 0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM chunk").fetchone()[0], before)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM chunk WHERE trim(text) = ''").fetchone()[0], 0)


class NewsIngestTests(unittest.TestCase):
    def setUp(self):
        self.conn = connect(":memory:")
        init_db(self.conn)

    def test_clean_text(self):
        t = clean_text("<p>Текст &amp; факты</p>\nЧитайте также: ерунда\n\n\n\nКонец\u200b")
        self.assertNotIn("Читайте", t)
        self.assertNotIn("<p>", t)
        self.assertIn("Текст & факты", t)
        self.assertNotIn("\u200b", t)

    def test_folder_idempotent_and_boilerplate_removed(self):
        s1 = ingest_news_folder(self.conn, str(DATA / "news"))
        s2 = ingest_news_folder(self.conn, str(DATA / "news"))
        self.assertEqual((s1["created"], s2["created"]), (3, 0))
        text = " ".join(r["text"] for r in self.conn.execute("SELECT text FROM chunk"))
        self.assertNotIn("Читайте также", text)
        news = repo.list_news(self.conn)
        self.assertEqual(len(news), 3)
        self.assertEqual(next(n for n in news if n["title"].startswith("ЦБ"))["doc_date"], "2026-09-12")

    def test_same_story_from_two_sources_not_duplicated(self):
        a, c1 = ingest_news(self.conn, title="ЦБ снизил ключевую ставку до 14,0%", text="Текст из Интерфакса.",
                            published_at="12.09.2026", source_name="Интерфакс")
        b, c2 = ingest_news(self.conn, title="ЦБ снизил ключевую ставку до 14,0%!", text="Совсем другой текст РБК.",
                            published_at="2026-09-12", source_name="РБК")
        self.assertTrue(c1)
        self.assertFalse(c2)
        self.assertEqual(a, b)
        self.assertEqual(len(repo.list_news(self.conn)), 1)

    def test_different_news_not_merged_and_validation(self):
        ingest_news(self.conn, title="ЦБ снизил ключевую ставку до 14,0%", text="а", published_at="12.09.2026")
        _, created = ingest_news(self.conn, title="Цены на бензин выросли на неделе", text="б", published_at="12.09.2026")
        self.assertTrue(created)
        with self.assertRaises(ValueError):
            ingest_news(self.conn, title="x", text="   ")
        with self.assertRaises(ValueError):
            ingest_news(self.conn, title="x", text="я" * 20_001)


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.conn, _ = make_env()

    def test_okved_longest_prefix(self):
        self.assertEqual(match_okved("46.71")["tag"], "fuel_trade")
        self.assertEqual(match_okved("46.90")["tag"], "wholesale")
        self.assertEqual(match_okved("43.21")["tag"], "construction")
        self.assertEqual(match_okved("52.10")["tag"], "logistics")
        self.assertIsNone(match_okved("99.99"))
        self.assertIsNone(match_okved(None))

    def test_demo_clients_have_different_meaningful_tags(self):
        p1 = build_profile(self.conn, "U_1465")
        p2 = build_profile(self.conn, "U_51606")
        p3 = build_profile(self.conn, "U_57706")
        self.assertEqual(p1.tag_names(), {"fuel_trade", "debt_sensitive", "fx_exposed", "group_member", "large_scale"})
        self.assertEqual(p2.tag_names(), {"construction", "debt_sensitive", "group_member", "large_scale"})
        self.assertEqual(p3.tag_names(), {"it", "large_scale"})
        for p in (p1, p2, p3):
            self.assertTrue(all(t.evidence for t in p.tags))
        self.assertIn("кредит", " ".join(p1.tag("debt_sensitive").evidence))
        self.assertIn("Китай", p1.tag("fx_exposed").evidence[0])

    def test_missing_values_and_hidden_fields(self):
        p = build_profile(self.conn, "U_701")
        self.assertNotIn("debt_sensitive", p.tag_names())
        self.assertIn("has_loan", p.unknown_features)
        self.assertNotIn("key_owner_mark", p.features)
        self.assertNotIn("key_owner_mark", p.to_llm_view())

    def test_unknown_client(self):
        with self.assertRaises(KeyError):
            build_profile(self.conn, "U_NOPE")


if __name__ == "__main__":
    unittest.main()
