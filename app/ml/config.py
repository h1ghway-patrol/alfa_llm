from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

_BASE = Path(__file__).parent


@lru_cache(maxsize=None)
def load_config(name: str) -> dict:
    return yaml.safe_load((_BASE / "config" / name).read_text(encoding="utf-8"))


@lru_cache(maxsize=None)
def load_prompt(name: str) -> str:
    return (_BASE / "prompts" / name).read_text(encoding="utf-8")


def topic_names() -> list[str]:
    return [t["name"] for t in load_config("topics.yaml")["topics"]]
