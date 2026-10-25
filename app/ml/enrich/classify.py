from __future__ import annotations

import logging

from app.db import repositories as repo
from app.db.documents import save_classification
from app.ml.agent.safety import GUARD, truncate, wrap_untrusted
from app.ml.config import load_config, load_prompt, topic_names
from app.ml.llm.base import LLMError

log = logging.getLogger(__name__)
MAX_NEWS_CHARS = 6000
FALLBACK_TOPIC = "отраслевые события"


def validate_classification(raw) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("ожидался JSON-объект")
    allowed = set(topic_names())
    topics = [t for t in dict.fromkeys(raw.get("topics") or []) if t in allowed]
    if not topics:
        raise ValueError(f"topics должен содержать 1–3 темы из списка {sorted(allowed)}")
    entities = raw.get("entities") or []
    if not isinstance(entities, list) or not all(isinstance(e, str) for e in entities):
        raise ValueError("entities должен быть списком строк")
    facts = []
    for f in raw.get("key_facts") or []:
        if not isinstance(f, dict) or not isinstance(f.get("text"), str) or not f["text"].strip():
            raise ValueError("каждый key_fact должен быть объектом с полем text")
        facts.append({"text": f["text"].strip(), "value": f.get("value"), "unit": f.get("unit"),
                      "date": f.get("date")})
    imp = raw.get("importance")
    if isinstance(imp, bool) or not isinstance(imp, (int, float)) or not 0 <= imp <= 1:
        raise ValueError("importance должен быть числом от 0 до 1")
    return {"topics": topics[:3], "entities": entities[:20], "key_facts": facts[:10], "importance": float(imp)}


def keyword_fallback(title: str, text: str) -> dict:
    hay = f"{title}\n{text}".lower()
    scored = []
    for t in load_config("topics.yaml")["topics"]:
        hits = sum(hay.count(k) for k in t["keywords"])
        if hits:
            scored.append((hits, t["name"]))
    scored.sort(key=lambda x: -x[0])
    topics = [name for _, name in scored[:3]] or [FALLBACK_TOPIC]
    return {"topics": topics, "entities": [], "key_facts": [], "importance": 0.5}


def classify_news(conn, doc_id: int, llm=None, force: bool = False) -> dict:
    event = repo.get_event(conn, doc_id)
    if event is None:
        raise KeyError(f"Новость {doc_id} не найдена")
    if not force and event["topics"] and event["facts"]:
        return {"topics": event["topics"], **event["facts"]}
    text = "\n\n".join(c["text"] for c in repo.get_doc_chunks(conn, doc_id))
    result, method = None, "fallback"
    if llm is not None:
        sys_prompt = load_prompt("classify_system.txt").replace("{TOPICS}", "; ".join(topic_names()))
        messages = [{"role": "system", "content": sys_prompt + "\n" + GUARD},
                    {"role": "user", "content": "Заголовок: " + truncate(event["title"], 300) + "\n"
                     + wrap_untrusted("NEWS", text, MAX_NEWS_CHARS)}]
        try:
            result = llm.call("simple", messages, purpose="classify", validator=validate_classification).data
            method = "llm"
        except LLMError as e:
            log.warning("Классификация новости %s через LLM не удалась (%s), запасной режим", doc_id, e)
    if result is None:
        result = keyword_fallback(event["title"], text)
    facts = {k: result[k] for k in ("entities", "key_facts", "importance")} | {"method": method}
    save_classification(conn, doc_id, result["topics"], facts)
    return {"topics": result["topics"], **facts}
