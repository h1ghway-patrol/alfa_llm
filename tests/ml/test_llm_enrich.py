import json
import logging
import os
import threading
import unittest
from datetime import date
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest import mock

from app.db import repositories as repo
from app.db.connection import connect, init_db
from app.db.documents import add_document
from app.db.trace import usage_by_day
from app.ml.enrich.classify import classify_news, keyword_fallback, validate_classification
from app.ml.llm.base import BudgetExceeded, LLMError, LLMValidationError, extract_json
from app.ml.llm.client import LLMClient
from app.ml.llm.fake import FakeLLM
from app.ml.ranking.ranker import rank_all, rank_events
from app.ml.retrieval.bank_context import retrieve_bank_context
from tests.ml.helpers import TODAY, make_env


def need_ok(raw):
    if not isinstance(raw, dict) or raw.get("ok") is not True:
        raise ValueError("нужно {'ok': true}")
    return raw


MSG = [{"role": "user", "content": "привет"}]


class ExtractJsonTests(unittest.TestCase):
    def test_variants(self):
        self.assertEqual(extract_json('{"a": 1}'), {"a": 1})
        self.assertEqual(extract_json('```json\n{"a": 1}\n```'), {"a": 1})
        self.assertEqual(extract_json('Вот ответ: {"a": [1, 2]} готово'), {"a": [1, 2]})
        for bad in ("без json", '{"a": ', ""):
            with self.assertRaises(ValueError):
                extract_json(bad)


class BaseLLMTests(unittest.TestCase):
    def setUp(self):
        self.conn = connect(":memory:")
        init_db(self.conn)

    def test_repair_retry_then_success(self):
        llm = FakeLLM(self.conn, {"t": ["не json", {"ok": True}]})
        r = llm.call("simple", MSG, purpose="t", validator=need_ok)
        self.assertEqual(r.data, {"ok": True})
        self.assertEqual(len(llm.calls), 2)
        self.assertIn("не прошёл проверку", llm.calls[1]["messages"][-1]["content"])

    def test_two_invalid_answers_raise(self):
        llm = FakeLLM(self.conn, {"t": {"ok": False}})
        with self.assertRaises(LLMValidationError):
            llm.call("simple", MSG, purpose="t", validator=need_ok)
        self.assertEqual(len(llm.calls), 2)

    def test_cache_hit_costs_nothing(self):
        llm = FakeLLM(self.conn, {"t": {"ok": True}})
        llm.call("simple", MSG, purpose="t", validator=need_ok)
        r = llm.call("simple", MSG, purpose="t", validator=need_ok)
        self.assertTrue(r.cached)
        self.assertEqual((len(llm.calls), r.tokens_in), (1, 0))
        llm.call("simple", MSG, purpose="t", validator=need_ok, use_cache=False)
        self.assertEqual(len(llm.calls), 2)

    def test_usage_recorded_and_budget_blocks_call(self):
        llm = FakeLLM(self.conn, {"t": {"ok": True}})
        llm.call("simple", MSG, purpose="t", validator=need_ok)
        usage = usage_by_day(self.conn)
        self.assertEqual(len(usage), 1)
        self.assertGreater(usage[0]["tokens_in"] + usage[0]["tokens_out"], 0)
        llm.cfg["daily_token_limit"] = 10
        with self.assertRaises(BudgetExceeded):
            llm.call("simple", [{"role": "user", "content": "другой запрос"}], purpose="t")
        self.assertEqual(len(llm.calls), 1)

    def test_rub_budget(self):
        llm = FakeLLM(self.conn, {"t": {"ok": True}})
        llm.cfg.update({"budget_rub": 0.0001, "price_rub_per_1k": {"input": 100.0, "output": 100.0}})
        llm.call("simple", MSG, purpose="t")
        with self.assertRaises(BudgetExceeded):
            llm.call("simple", [{"role": "user", "content": "ещё"}], purpose="t")

    def test_unknown_role(self):
        with self.assertRaises(LLMError):
            FakeLLM(self.conn).call("nobody", MSG, purpose="classify")


class _Handler(BaseHTTPRequestHandler):
    log = {"hits": 0, "auth": []}

    def do_POST(self):
        _Handler.log["hits"] += 1
        _Handler.log["auth"].append(self.headers.get("Authorization"))
        self.rfile.read(int(self.headers["Content-Length"]))
        if _Handler.log["hits"] == 1:
            self.send_response(429)
            self.end_headers()
            return
        body = json.dumps({"choices": [{"message": {"content": '{"ok": true}'}}],
                           "usage": {"prompt_tokens": 12, "completion_tokens": 3}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


class RealClientTests(unittest.TestCase):
    def setUp(self):
        _Handler.log = {"hits": 0, "auth": []}
        self.server = HTTPServer(("127.0.0.1", 0), _Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.conn = connect(":memory:")
        init_db(self.conn)
        self.cfg = {"base_url": f"http://127.0.0.1:{self.server.server_port}/v1", "api_key_env": "TEST_LLM_KEY",
                    "timeout_s": 5, "retries": 3, "backoff_s": 0.01,
                    "roles": {"simple": {"model": "m", "max_tokens": 50}}}

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def test_retry_on_429_then_ok_with_usage(self):
        with mock.patch.dict(os.environ, {"TEST_LLM_KEY": "sk-secret-123"}):
            llm = LLMClient(self.conn, self.cfg, sleep=lambda s: None)
            r = llm.call("simple", MSG, purpose="t", validator=need_ok)
        self.assertEqual(_Handler.log["hits"], 2)
        self.assertEqual((r.tokens_in, r.tokens_out), (12, 3))
        self.assertEqual(_Handler.log["auth"][-1], "Bearer sk-secret-123")
        self.assertEqual(usage_by_day(self.conn)[0]["tokens_in"], 12)

    def test_missing_key_and_key_not_in_logs(self):
        env = {k: v for k, v in os.environ.items() if k != "TEST_LLM_KEY"}
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(LLMError) as cm:
                LLMClient(self.conn, self.cfg).call("simple", MSG, purpose="t")
        self.assertIn("TEST_LLM_KEY", str(cm.exception))
        self.cfg["base_url"] = "http://127.0.0.1:9/v1"
        with mock.patch.dict(os.environ, {"TEST_LLM_KEY": "sk-secret-123"}):
            with self.assertLogs("app.ml.llm.client", level="WARNING") as logs:
                with self.assertRaises(LLMError) as cm:
                    LLMClient(self.conn, self.cfg, sleep=lambda s: None).call("simple", MSG, purpose="t")
        self.assertNotIn("sk-secret-123", "\n".join(logs.output) + str(cm.exception))


class ClassifyTests(unittest.TestCase):
    def setUp(self):
        self.conn = connect(":memory:")
        init_db(self.conn)
        self.doc, _ = add_document(self.conn, kind="news", title="ЦБ снизил ключевую ставку", source_name="x",
                                   doc_date="2026-09-12", chunks=[{"text": "Банк России снизил ключевую ставку до 14,0%."}])

    GOOD = {"topics": ["ключевая ставка и ДКП"], "entities": ["Банк России"],
            "key_facts": [{"text": "Ставка снижена до 14,0%", "value": 14.0, "unit": "%", "date": "2026-09-12"}],
            "importance": 0.9}

    def test_llm_path_saves_topics_and_facts(self):
        llm = FakeLLM(self.conn, {"classify": self.GOOD})
        res = classify_news(self.conn, self.doc, llm)
        ev = repo.get_event(self.conn, self.doc)
        self.assertEqual(ev["topics"], ["ключевая ставка и ДКП"])
        self.assertEqual(ev["facts"]["importance"], 0.9)
        self.assertEqual(ev["facts"]["method"], "llm")
        self.assertEqual(res["topics"], ev["topics"])

    def test_not_called_twice(self):
        llm = FakeLLM(self.conn, {"classify": self.GOOD})
        classify_news(self.conn, self.doc, llm)
        classify_news(self.conn, self.doc, llm)
        self.assertEqual(len(llm.calls), 1)

    def test_invalid_then_repaired(self):
        bad = {**self.GOOD, "topics": ["выдуманная тема"]}
        llm = FakeLLM(self.conn, {"classify": [bad, self.GOOD]})
        classify_news(self.conn, self.doc, llm)
        self.assertEqual(len(llm.calls), 2)
        self.assertEqual(repo.get_event(self.conn, self.doc)["facts"]["method"], "llm")

    def test_fallback_when_llm_keeps_failing(self):
        llm = FakeLLM(self.conn, {"classify": "это не json"})
        classify_news(self.conn, self.doc, llm)
        ev = repo.get_event(self.conn, self.doc)
        self.assertEqual(ev["facts"]["method"], "fallback")
        self.assertEqual(ev["topics"][0], "ключевая ставка и ДКП")

    def test_fallback_without_llm_and_default_topic(self):
        self.assertEqual(keyword_fallback("Погода", "Сегодня солнечно")["topics"], ["отраслевые события"])
        self.assertIn("нефть и топливо", keyword_fallback("Бензин дорожает", "нефть")["topics"])

    def test_validation_rules(self):
        with self.assertRaises(ValueError):
            validate_classification({**self.GOOD, "importance": 5})
        with self.assertRaises(ValueError):
            validate_classification({**self.GOOD, "topics": []})
        self.assertEqual(len(validate_classification({**self.GOOD, "topics": ["инфляция"] * 2 +
                                                      ["курс и валюта", "бюджет и ОФЗ", "рынок труда"]})["topics"]), 3)


class RetrievalTests(unittest.TestCase):
    def setUp(self):
        self.conn, self.ids = make_env()

    def event(self, title="Rate"):
        return repo.get_event(self.conn, self.ids["ЦБ снизил"])

    def test_rate_event_finds_macro_and_keeps_both_versions(self):
        res = retrieve_bank_context(self.conn, self.event(), k=6)
        titles = [r["doc_title"] for r in res]
        self.assertTrue(titles[0].startswith(("Макро", "Ставка")))
        self.assertTrue(any("Макро" in t for t in titles) and any("Ставка: предыдущий" in t for t in titles),
                        "оба документа со ставкой (14,0% и 13,5%) должны вернуться с датами")
        self.assertTrue(all(r["doc_date"] for r in res if "Золото" not in r["doc_title"]))

    def test_outdated_goes_after_actual(self):
        res = retrieve_bank_context(self.conn, self.event(), query="ставка кредит", k=10)
        flags = [r["freshness"] == "outdated" for r in res]
        self.assertTrue(any(flags), "материал 2021 должен быть найден")
        self.assertEqual(flags, sorted(flags))
        self.assertNotEqual(res[0]["freshness"], "outdated")
        top = retrieve_bank_context(self.conn, self.event(), k=3)
        self.assertNotEqual(top[0]["freshness"], "outdated")

    def test_near_duplicates_removed_but_different_numbers_kept(self):
        add_document(self.conn, kind="bank", title="Копия 1", source_name="b", doc_date="2026-07-01", status="actual",
                     chunks=[{"text": "Квантовая турбина ускорила выпуск изделий на заводе."}])
        add_document(self.conn, kind="bank", title="Копия 2", source_name="b", doc_date="2026-07-02", status="actual",
                     chunks=[{"text": "Квантовая турбина ускорила выпуск изделий на заводе."}])
        add_document(self.conn, kind="bank", title="Версия", source_name="b", doc_date="2026-07-03", status="actual",
                     chunks=[{"text": "Квантовая турбина ускорила выпуск изделий на заводе на 15%."}])
        res = retrieve_bank_context(self.conn, {"title": "квантовая турбина", "topics": []}, query="квантовая турбина", k=10)
        titles = sorted(r["doc_title"] for r in res)
        self.assertEqual(len([t for t in titles if t.startswith("Копия")]), 1)
        self.assertIn("Версия", titles)


class RankingTests(unittest.TestCase):
    def setUp(self):
        self.conn, self.ids = make_env()

    def feed(self, client):
        rank_events(self.conn, client, TODAY)
        return {i["event_id"]: i for i in repo.get_feed(self.conn, client)}

    def test_feeds_differ_between_clients(self):
        f1, f2, f3 = self.feed("U_1465"), self.feed("U_51606"), self.feed("U_57706")
        rate, fuel, fx = (self.ids[k] for k in ("ЦБ снизил", "Цены на бензин", "Курс юаня"))
        self.assertEqual(set(f1), {rate, fuel, fx})
        self.assertEqual(set(f2), {rate, fuel})
        self.assertGreater(f2[rate]["relevance_score"], f2[fuel]["relevance_score"])
        self.assertEqual(f3, {})

    def test_reasons_are_real_and_limited(self):
        f1 = self.feed("U_1465")
        for item in f1.values():
            self.assertTrue(1 <= len(item["relevance_reasons"]) <= 3)
        rate_reasons = " ".join(f1[self.ids["ЦБ снизил"]]["relevance_reasons"])
        self.assertIn("кредит", rate_reasons)
        fx_reasons = " ".join(f1[self.ids["Курс юаня"]]["relevance_reasons"])
        self.assertIn("ВЭД", fx_reasons.replace("внешнеэкономическую деятельность", "ВЭД"))
        no_fx = self.feed("U_51606")
        self.assertNotIn("ВЭД", " ".join(r for i in no_fx.values() for r in i["relevance_reasons"]))

    def test_rate_news_higher_for_borrower_than_for_it_company(self):
        borrower = rank_events(self.conn, "U_51606", TODAY, save=False)
        self.assertEqual(borrower[0]["doc_id"], self.ids["ЦБ снизил"])
        self.assertEqual(rank_events(self.conn, "U_57706", TODAY, save=False), [])

    def test_freshness_matters_but_does_not_create_relevance(self):
        fresh = rank_events(self.conn, "U_1465", TODAY, save=False)
        stale = rank_events(self.conn, "U_1465", date(2027, 6, 1), save=False)
        score = lambda lst, d: next(r["score"] for r in lst if r["doc_id"] == d)
        rate = self.ids["ЦБ снизил"]
        self.assertGreater(score(fresh, rate), score(stale, rate))
        self.assertTrue(all(r["score"] <= 1 for r in fresh))

    def test_rank_all_and_repeat_safe(self):
        sizes = rank_all(self.conn, today=TODAY)
        self.assertEqual(sizes, {"U_1465": 3, "U_51606": 2, "U_57706": 0})
        self.assertEqual(rank_all(self.conn, today=TODAY), sizes)


if __name__ == "__main__":
    unittest.main()
