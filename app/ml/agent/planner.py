from __future__ import annotations

import logging

from app.ml.agent.safety import GUARD, wrap_untrusted
from app.ml.agent.state import AgentState
from app.ml.agent.tools import TOOL_NAMES
from app.ml.config import load_prompt
from app.ml.llm.base import LLMError

log = logging.getLogger(__name__)


def validate_plan(raw, max_steps: int) -> list[dict]:
    steps = raw.get("steps") if isinstance(raw, dict) else None
    if not isinstance(steps, list) or not steps:
        raise ValueError('нужен объект {"steps": [...]} с непустым списком')
    if len(steps) > max_steps:
        raise ValueError(f"шагов больше {max_steps}")
    out = []
    for s in steps:
        if not isinstance(s, dict) or s.get("tool") not in TOOL_NAMES:
            raise ValueError(f"tool должен быть одним из {list(TOOL_NAMES)}")
        args = s.get("args", {})
        if not isinstance(args, dict):
            raise ValueError("args должен быть объектом")
        out.append({"tool": s["tool"], "args": args, "why": str(s.get("why", ""))[:200]})
    return out


def default_plan(state: AgentState) -> list[dict]:
    title = (state.event or {}).get("title", "")
    return [{"tool": "get_profile", "args": {}, "why": "контекст клиента"},
            {"tool": "get_event", "args": {}, "why": "факты события"},
            {"tool": "retrieve_bank_context", "args": {}, "why": "позиция банка"},
            {"tool": "search_news", "args": {"query": title or "новости", "k": 3}, "why": "связанные новости"}]


def make_plan(llm, conn, state: AgentState, max_steps: int, recorder) -> list[dict]:
    from app.db import repositories as repo
    ev = repo.get_event(conn, state.doc_id)
    state.event = state.event or ev
    plan, source = None, "default"
    if llm is not None and ev is not None:
        sys_prompt = load_prompt("plan_system.txt").replace("{MAX_STEPS}", str(max_steps))
        messages = [{"role": "system", "content": sys_prompt + "\n" + GUARD},
                    {"role": "user", "content": "Новость: " + wrap_untrusted("NEWS", ev["title"], 300)
                     + "\nТемы: " + ", ".join(ev["topics"]) + "\nСоставь план."}]
        try:
            plan = llm.call("universal", messages, purpose="plan", recorder=recorder,
                            validator=lambda r: validate_plan(r, max_steps)).data
            source = "llm"
        except LLMError as e:
            log.warning("План от LLM не получен (%s), используется план по умолчанию", e)
    if plan is None:
        plan = default_plan(state)
    with recorder.step("plan", input={"source": source}) as s:
        s.set_output({"steps": plan})
    return plan
