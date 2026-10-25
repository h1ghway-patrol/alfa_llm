from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request

from app.ml.llm.base import BaseLLM, LLMError, estimate_tokens

log = logging.getLogger(__name__)
RETRY_STATUSES = {429, 500, 502, 503, 504}


class LLMClient(BaseLLM):
    def __init__(self, conn=None, config: dict | None = None, sleep=time.sleep):
        super().__init__(conn, config)
        self._sleep = sleep

    def _api_key(self) -> str:
        key = os.environ.get(self.cfg["api_key_env"])
        if not key:
            raise LLMError(f"Не задана переменная окружения {self.cfg['api_key_env']} с ключом LLM")
        return key

    def _complete(self, role: str, messages: list[dict], purpose: str) -> tuple[str, int, int]:
        rc = self._role(role)
        body = json.dumps({"model": rc["model"], "messages": messages,
                           "temperature": rc.get("temperature", 0.0),
                           "max_tokens": rc.get("max_tokens", 1000)}).encode()
        req = urllib.request.Request(
            self.cfg["base_url"].rstrip("/") + "/chat/completions", data=body, method="POST",
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + self._api_key()})
        retries = int(self.cfg.get("retries", 3))
        last: Exception | None = None
        for attempt in range(retries):
            try:
                with urllib.request.urlopen(req, timeout=self.cfg.get("timeout_s", 60)) as resp:
                    payload = json.loads(resp.read().decode())
                text = payload["choices"][0]["message"]["content"] or ""
                usage = payload.get("usage") or {}
                t_in = int(usage.get("prompt_tokens") or estimate_tokens(messages))
                t_out = int(usage.get("completion_tokens") or len(text) // 3 + 1)
                return text, t_in, t_out
            except urllib.error.HTTPError as e:
                e.close()
                last = e
                if e.code not in RETRY_STATUSES:
                    raise LLMError(f"LLM вернула HTTP {e.code}") from None
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                last = e
            except (KeyError, IndexError, ValueError) as e:
                raise LLMError(f"Неожиданный формат ответа LLM: {type(e).__name__}") from None
            log.warning("LLM-запрос не удался (попытка %d/%d): %s", attempt + 1, retries, type(last).__name__)
            if attempt < retries - 1:
                self._sleep(float(self.cfg.get("backoff_s", 1.5)) * (2 ** attempt))
        raise LLMError(f"LLM недоступна после {retries} попыток: {type(last).__name__}")
