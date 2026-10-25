from __future__ import annotations

import logging
from datetime import date, datetime

from app.db import repositories as repo
from app.ml.config import load_config
from app.ml.profile.builder import build_profile, match_okved

log = logging.getLogger(__name__)


def client_interest(profile) -> tuple[set[str], set[str]]:
    cfg = load_config("ranking.yaml")
    industry: set[str] = set()
    rule = match_okved(profile.features.get("okved_code"))
    if rule:
        industry = set(rule["topics"])
    topics = set(industry)
    for t in profile.tags:
        topics |= set(cfg["tag_topics"].get(t.name, []))
    return topics, industry


def _age_days(doc_date: str | None, today: date) -> int | None:
    if not doc_date:
        return None
    return max(0, (today - datetime.strptime(doc_date[:10], "%Y-%m-%d").date()).days)


def score_event(profile, event: dict, today: date) -> dict | None:
    cfg = load_config("ranking.yaml")
    w = cfg["weights"]
    ev_topics = set(event.get("topics") or [])
    interest, industry = client_interest(profile)

    overlap = len(ev_topics & interest) / len(ev_topics) if ev_topics else 0.0
    exposure, exp_reason = 0.0, None
    for rule in cfg["exposure"]:
        tag = profile.tag(rule["tag"])
        if rule["topic"] in ev_topics and tag and rule["weight"] > exposure:
            exposure = rule["weight"]
            exp_reason = rule["reason"].format(evidence=tag.evidence[0] if tag.evidence else tag.label)
    ind = 1.0 if ev_topics & industry else 0.0
    if overlap == 0 and exposure == 0 and ind == 0:
        return None

    age = _age_days(event.get("doc_date"), today)
    freshness = 0.5 if age is None else 0.5 ** (age / cfg["freshness_half_life_days"])
    importance = float((event.get("facts") or {}).get("importance", 0.5))
    feats = {"topic_overlap": overlap, "exposure": exposure, "industry": ind,
             "freshness": freshness, "importance": importance}
    contrib = {k: w[k] * v for k, v in feats.items()}
    score = round(sum(contrib.values()) / sum(w.values()), 4)

    reasons: list[tuple[float, str]] = []
    if exp_reason:
        reasons.append((contrib["exposure"], exp_reason))
    if ind:
        label = profile.tag(match_okved(profile.features.get("okved_code"))["tag"]).label
        reasons.append((contrib["industry"], f"Новость затрагивает отрасль клиента: {label}"))
    if overlap > 0:
        shared = ", ".join(sorted(ev_topics & interest))
        reasons.append((contrib["topic_overlap"], f"Тема «{shared}» совпадает с интересами клиента по профилю"))
    if freshness >= 0.5 and age is not None:
        reasons.append((contrib["freshness"], f"Свежая новость ({age} дн. назад)"))
    if importance >= 0.7:
        reasons.append((contrib["importance"], "Событие оценено как высокозначимое"))
    reasons.sort(key=lambda r: -r[0])
    return {"score": score, "reasons": [r for _, r in reasons[:cfg["max_reasons"]]], "features": feats}


def rank_events(conn, client_id: str, today: date | None = None, save: bool = True) -> list[dict]:
    cfg = load_config("ranking.yaml")
    today = today or date.today()
    profile = build_profile(conn, client_id)
    ranked = []
    for ev in repo.list_news(conn):
        res = score_event(profile, ev, today)
        if res and res["score"] >= cfg["threshold"]:
            ranked.append({"doc_id": ev["id"], **res})
    ranked.sort(key=lambda r: -r["score"])
    if save:
        repo.save_relevance(conn, client_id,
                            [{"doc_id": r["doc_id"], "score": min(1.0, r["score"]), "reasons": r["reasons"]}
                             for r in ranked])
    return ranked


def rank_all(conn, demo_only: bool = True, today: date | None = None) -> dict[str, int]:
    clients = repo.list_clients(conn, demo_only=demo_only, limit=10_000)
    return {c["id"]: len(rank_events(conn, c["id"], today)) for c in clients}
