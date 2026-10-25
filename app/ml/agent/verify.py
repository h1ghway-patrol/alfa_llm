from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.db.search import lemmatize
from app.ml.agent.state import AgentState
from app.ml.types import Insight

_NUM = re.compile(r"(?<!\w)(\d+(?:[.,]\d+)?)(\s?%)?(?!\w)")
CLAIM_FIXABLE = {"no_source", "bad_source", "number_not_in_source", "stale_version"}
CONFLICT_JACCARD = 0.25


@dataclass
class Report:
    issues: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def add(self, code, block, index, message):
        self.issues.append({"code": code, "block": block, "index": index, "message": message})

    def to_dict(self) -> dict:
        return {"ok": not self.issues, "issues": self.issues, "notes": self.notes}


def _values(text: str) -> set[float]:
    return {float(m[1].replace(",", ".")) for m in _NUM.finditer(text)}


def _checked_values(text: str) -> set[float]:
    out = set()
    for m in _NUM.finditer(text):
        v = float(m[1].replace(",", "."))
        if m[2] or v != int(v) or v > 31:
            out.add(v)
    return out


def _pool(state: AgentState, kind: str) -> dict:
    return state.news_pool if kind == "fact" else state.bank_pool


def _conflicts(state: AgentState) -> list[tuple[dict, dict]]:
    chunks = list(state.bank_pool.values())
    out = []
    for i, a in enumerate(chunks):
        for b in chunks[i + 1:]:
            if a["doc_id"] == b["doc_id"] or not a.get("doc_date") or not b.get("doc_date") \
                    or a["doc_date"] == b["doc_date"]:
                continue
            la, lb = set(lemmatize(a["text"])), set(lemmatize(b["text"]))
            if la and lb and len(la & lb) / len(la | lb) >= CONFLICT_JACCARD \
                    and _checked_values(a["text"]) != _checked_values(b["text"]):
                out.append((a, b) if a["doc_date"] < b["doc_date"] else (b, a))
    return out


def verify_insight(insight: Insight, state: AgentState) -> Report:
    r = Report()
    blocks = insight.blocks()

    for key in ("what_happened", "why_it_matters", "actions", "bank_view", "basis"):
        if not blocks[key]:
            r.add("empty_block", key, 0, f"блок {key} пуст")
    if not blocks["consequences.risks"] and not blocks["consequences.opportunities"]:
        r.add("empty_block", "consequences.risks", 0, "в блоке consequences нет ни рисков, ни возможностей")

    cited_bank: set[int] = set()
    refs_ok = set(state.profile.feature_refs()) if state.profile else set()
    has_client = False
    for block, idx, c in insight.iter_claims():
        if c.kind in ("fact", "bank"):
            pool = _pool(state, c.kind)
            if not c.source_ids:
                r.add("no_source", block, idx, f"утверждение вида {c.kind} без source_ids")
                continue
            missing = [i for i in c.source_ids if i not in pool]
            if missing:
                where = "новостных" if c.kind == "fact" else "банковских"
                r.add("bad_source", block, idx, f"source_ids {missing} нет среди найденных {where} фрагментов")
                continue
            source_text = " ".join(pool[i]["text"] for i in c.source_ids)
            absent = sorted(v for v in _checked_values(c.text) if v not in _values(source_text))
            if absent:
                r.add("number_not_in_source", block, idx,
                      f"числа {absent} нет в тексте указанного источника")
                continue
            if c.kind == "bank":
                cited_bank.update(c.source_ids)
        elif c.kind == "client":
            good = [f for f in c.client_features if f in refs_ok]
            if not good:
                r.add("bad_source", block, idx, "утверждение вида client без допустимых признаков клиента")
            else:
                has_client = True
        elif c.source_ids:
            r.add("bad_source", block, idx, "у утверждения вида ai не должно быть source_ids")
    if not has_client and not any(i["code"] == "bad_source" and "client" in i["message"] for i in r.issues):
        r.add("no_client_feature", "why_it_matters", 0, "ни одно утверждение не опирается на признак клиента")

    for old, new in _conflicts(state):
        if old["chunk_id"] in cited_bank:
            for block, idx, c in insight.iter_claims():
                if c.kind == "bank" and old["chunk_id"] in c.source_ids:
                    r.add("stale_version", block, idx,
                          f"использован более ранний документ ({old['doc_date']}), есть более поздний ({new['doc_date']})")
        if old["chunk_id"] in cited_bank or new["chunk_id"] in cited_bank:
            r.notes.append(f"В материалах банка разные значения показателя: «{old.get('title')}» "
                           f"({old['doc_date']}) и «{new.get('title')}» ({new['doc_date']}); "
                           f"использован более поздний документ.")

    for cid in sorted(cited_bank):
        ch = state.bank_pool[cid]
        if ch.get("status") == "outdated":
            r.notes.append(f"Использован устаревший материал банка: «{ch.get('title')}» ({ch.get('doc_date')}).")
    return r


def downgrade(insight: Insight, issues: list[dict]) -> list[str]:
    notes = []
    blocks = insight.blocks()
    for i in issues:
        if i["code"] in CLAIM_FIXABLE:
            c = blocks[i["block"]][i["index"]]
            if c.kind in ("fact", "bank", "client"):
                c.kind, c.source_ids, c.client_features = "ai", [], []
                notes.append(f"Утверждение в блоке «{i['block']}» не подтверждено источником и помечено как вывод AI ({i['code']}).")
            elif c.kind == "ai":
                c.source_ids = []
        elif i["code"] == "empty_block":
            notes.append(f"Блок «{i['block']}» не удалось заполнить: {i['message']}.")
        elif i["code"] == "no_client_feature":
            notes.append("Вывод не опирается напрямую на признаки клиента.")
    return list(dict.fromkeys(notes))
