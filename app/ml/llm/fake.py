from __future__ import annotations

import json
import re
from typing import Any, Callable

from app.ml.llm.base import BaseLLM, estimate_tokens


def _default_classify(messages) -> dict:
    return {"topics": ["отраслевые события"], "entities": [], "key_facts": [], "importance": 0.5}


def _default_plan(messages) -> dict:
    return {"steps": [{"tool": "get_profile", "args": {}, "why": "нужен контекст клиента"},
                      {"tool": "get_event", "args": {}, "why": "нужны факты события"},
                      {"tool": "retrieve_bank_context", "args": {}, "why": "позиция банка"}]}


def _default_generate(messages) -> dict:
    prompt = messages[-1]["content"] if messages[-1]["role"] == "user" else messages[-2]["content"]
    news = [int(x) for x in re.findall(r"\[N:(\d+)\]", prompt)]
    bank = [int(x) for x in re.findall(r"\[B:(\d+)\]", prompt)]
    m = re.search(r"Допустимые признаки клиента: (.*)", prompt)
    feats = [x.strip() for x in m[1].split(",") if x.strip()][:1] if m else []
    claim = lambda t, k, ids=(), f=(): {"text": t, "kind": k, "source_ids": list(ids), "client_features": list(f)}
    return {
        "what_happened": [claim("Событие описано в новостном материале.", "fact", news[:1])] if news else
                         [claim("Подробности события в источнике не найдены.", "ai")],
        "why_it_matters": [claim("Событие связано с профилем клиента.", "client", (), feats)] if feats else
                          [claim("Влияние на клиента оценено по общим признакам.", "ai")],
        "consequences": {"risks": [claim("Возможно изменение условий для бизнеса клиента.", "ai")],
                         "opportunities": [claim("Возможен пересмотр планов финансирования.", "ai")]},
        "actions": [claim("Обсудить с клиентом влияние события на планы.", "ai")],
        "bank_view": [claim("Аналитика банка затрагивает эту тему.", "bank", bank[:1])] if bank else
                     [claim("Аналитика банка эту тему отдельно не комментировала.", "ai")],
        "basis": ([claim("Новостной материал.", "fact", news[:1])] if news else []) +
                 ([claim("Аналитика банка.", "bank", bank[:1])] if bank else []) or [claim("Общие данные.", "ai")],
        "data_quality_notes": [],
    }


class FakeLLM(BaseLLM):

    def __init__(self, conn=None, handlers: dict[str, Any] | None = None, config: dict | None = None):
        super().__init__(conn, config or {"roles": {r: {"model": f"fake-{r}", "max_tokens": 100}
                                                    for r in ("simple", "universal", "complex", "verify")}})
        self.handlers: dict[str, Any] = {"classify": _default_classify, "plan": _default_plan,
                                         "generate": _default_generate}
        self.handlers.update(handlers or {})
        self.calls: list[dict] = []

    def _complete(self, role, messages, purpose):
        self.calls.append({"role": role, "purpose": purpose, "messages": messages})
        h: Callable | Any = self.handlers.get(purpose)
        if h is None:
            raise KeyError(f"FakeLLM: нет обработчика для purpose={purpose!r}")
        out = h(messages) if callable(h) else h
        if isinstance(out, list):
            out = out[min(sum(1 for c in self.calls if c["purpose"] == purpose) - 1, len(out) - 1)]
        text = out if isinstance(out, str) else json.dumps(out, ensure_ascii=False)
        return text, estimate_tokens(messages), len(text) // 3 + 1
