from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from typing import Any, Callable

from app.db import repositories as repo
from app.db.trace import can_spend, total_cost
from app.ml.config import load_config


def apply_env_limits(cfg: dict) -> dict:
    out = dict(cfg)
    raw = os.environ.get("DAILY_TOKEN_LIMIT_TOKENS", "").strip()
    if raw:
        try:
            value = int(raw)
        except ValueError:
            raise ValueError(f"DAILY_TOKEN_LIMIT_TOKENS должен быть целым числом, получено {raw!r}") from None
        if value <= 0:
            raise ValueError(f"DAILY_TOKEN_LIMIT_TOKENS должен быть больше 0, получено {raw!r}")
        out["daily_token_limit"] = value
    raw = os.environ.get("BUDGET_RUB", "").strip()
    if raw:
        try:
            value = float(raw)
        except ValueError:
            raise ValueError(f"BUDGET_RUB должен быть числом, получено {raw!r}") from None
        if value <= 0:
            raise ValueError(f"BUDGET_RUB должен быть больше 0, получено {raw!r}")
        out["budget_rub"] = value
    return out


class LLMError(Exception):
    pass


class BudgetExceeded(LLMError):
    pass


class LLMValidationError(LLMError):
    pass


@dataclass
class LLMResponse:
    text: str
    data: Any = None
    tokens_in: int = 0
    tokens_out: int = 0
    model: str | None = None
    cached: bool = False


def extract_json(text: str) -> Any:
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.I)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    start = min([i for i in (t.find("{"), t.find("[")) if i >= 0], default=-1)
    if start < 0:
        raise ValueError("в ответе нет JSON")
    closer = "}" if t[start] == "{" else "]"
    end = t.rfind(closer)
    if end <= start:
        raise ValueError("JSON в ответе не закрыт")
    try:
        return json.loads(t[start:end + 1])
    except json.JSONDecodeError as e:
        raise ValueError(f"невалидный JSON: {e}") from None


def estimate_tokens(messages: list[dict]) -> int:
    return sum(len(m.get("content", "")) for m in messages) // 3 + 1


class BaseLLM:
    def __init__(self, conn=None, config: dict | None = None):
        self.conn = conn
        self.cfg = config if config is not None else apply_env_limits(load_config("llm.yaml"))
        self._mem_cache: dict[str, str] = {}

    def _complete(self, role: str, messages: list[dict], purpose: str) -> tuple[str, int, int]:
        raise NotImplementedError

    def _role(self, role: str) -> dict:
        try:
            return self.cfg["roles"][role]
        except KeyError:
            raise LLMError(f"Неизвестная роль модели: {role!r}") from None

    def _check_budget(self, est_tokens: int) -> None:
        if self.conn is None:
            return
        limit = self.cfg.get("daily_token_limit")
        if limit and not can_spend(self.conn, est_tokens, limit):
            raise BudgetExceeded("Исчерпан дневной лимит токенов")
        price = self.cfg.get("price_rub_per_1k") or {}
        budget = self.cfg.get("budget_rub")
        if budget and price.get("input") is not None and price.get("output") is not None:
            if total_cost(self.conn, price["input"], price["output"]) >= budget:
                raise BudgetExceeded("Исчерпан бюджет в рублях")

    def _cache_get(self, key: str) -> str | None:
        return repo.llm_cache_get(self.conn, key) if self.conn is not None else self._mem_cache.get(key)

    def _cache_put(self, key: str, text: str) -> None:
        if self.conn is not None:
            repo.llm_cache_put(self.conn, key, text)
        else:
            self._mem_cache[key] = text

    def call(self, role: str, messages: list[dict], *, purpose: str = "llm",
             validator: Callable[[Any], Any] | None = None, recorder=None,
             use_cache: bool = True) -> LLMResponse:
        role_cfg = self._role(role)
        model = role_cfg["model"]
        key = hashlib.sha256(json.dumps({"m": model, "msgs": messages, "p": purpose},
                                        ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        if use_cache and (hit := self._cache_get(key)) is not None:
            try:
                data = validator(extract_json(hit)) if validator else None
                return LLMResponse(hit, data, 0, 0, model, cached=True)
            except ValueError:
                pass

        self._check_budget(estimate_tokens(messages) + role_cfg.get("max_tokens", 0))
        msgs = list(messages)
        for attempt in (0, 1):
            text, t_in, t_out = self._timed_complete(role, msgs, purpose, model, recorder)
            if validator is None:
                self._cache_put(key, text)
                return LLMResponse(text, None, t_in, t_out, model)
            try:
                data = validator(extract_json(text))
            except ValueError as e:
                if attempt == 1:
                    raise LLMValidationError(f"Ответ модели не прошёл проверку: {e}") from None
                msgs = msgs + [{"role": "assistant", "content": text},
                               {"role": "user", "content": f"Ответ не прошёл проверку: {e}. "
                                                           "Верни только исправленный корректный JSON."}]
                continue
            self._cache_put(key, text)
            return LLMResponse(text, data, t_in, t_out, model)
        raise LLMValidationError("недостижимо")

    def _timed_complete(self, role, msgs, purpose, model, recorder):
        if recorder is not None:
            with recorder.step("llm", model=model, input={"purpose": purpose, "role": role}) as s:
                text, t_in, t_out = self._complete(role, msgs, purpose)
                s.set_tokens(t_in, t_out)
                s.set_output({"chars": len(text)})
            return text, t_in, t_out
        text, t_in, t_out = self._complete(role, msgs, purpose)
        if self.conn is not None:
            repo.record_llm_usage(self.conn, purpose, model, t_in, t_out)
        return text, t_in, t_out
