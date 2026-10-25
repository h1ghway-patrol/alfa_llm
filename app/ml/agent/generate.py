from __future__ import annotations

from app.ml.agent.safety import GUARD, truncate, wrap_untrusted
from app.ml.agent.state import AgentState
from app.ml.config import load_config, load_prompt
from app.ml.types import Insight

MAX_NEWS_CHUNKS = 6
MAX_BANK_CHUNKS = 8
MAX_RELATED = 3


def build_messages(state: AgentState, issues: list[dict] | None = None) -> list[dict]:
    limit = load_config("agent.yaml")["chunk_chars_in_prompt"]
    own = [c for c in state.news_pool.values() if c["doc_id"] == state.doc_id][:MAX_NEWS_CHUNKS]
    related = [c for c in state.news_pool.values() if c["doc_id"] != state.doc_id][:MAX_RELATED]
    bank = sorted(state.bank_pool.values(), key=lambda c: -c.get("score", 0))[:MAX_BANK_CHUNKS]

    parts = [f"Клиент (профиль): {state.profile.to_llm_view()}",
             "Допустимые признаки клиента: " + ", ".join(state.profile.feature_refs()),
             f"Новость: {state.event['title']} (дата: {state.event.get('doc_date') or 'не указана'})"]
    parts.append("Фрагменты новости:\n" + "\n".join(
        f"[N:{c['chunk_id']}] " + wrap_untrusted("NEWS", truncate(c["text"], limit), limit + 50) for c in own))
    if related:
        parts.append("Связанные новости:\n" + "\n".join(
            f"[N:{c['chunk_id']}] ({c.get('title', '')}) "
            + wrap_untrusted("NEWS", truncate(c["text"], limit), limit + 50) for c in related))
    if bank:
        parts.append("Фрагменты аналитики банка:\n" + "\n".join(
            f"[B:{c['chunk_id']}] ({c.get('title') or c.get('doc_title')}, дата: {c.get('doc_date') or 'нет'}, "
            f"{'УСТАРЕЛ' if c.get('status') == 'outdated' else 'актуален'}) "
            + wrap_untrusted("BANK", truncate(c["text"], limit), limit + 50) for c in bank))
    else:
        parts.append("Фрагментов аналитики банка по теме НЕ найдено.")
    if issues:
        parts.append("В прошлой версии найдены проблемы, исправь их:\n" + "\n".join(
            f"- {i['block']}[{i['index']}]: {i['message']}" for i in issues))
    parts.append("Составь интерпретацию по правилам. В source_ids указывай целые числа из [N:..] и [B:..].")
    return [{"role": "system", "content": load_prompt("generate_system.txt") + "\n" + GUARD},
            {"role": "user", "content": "\n\n".join(parts)}]


def generate_insight(llm, state: AgentState, recorder, issues: list[dict] | None = None) -> Insight:
    return llm.call("complex", build_messages(state, issues), purpose="generate",
                    recorder=recorder, validator=Insight.from_dict,
                    use_cache=not issues).data
