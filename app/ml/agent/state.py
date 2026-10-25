from __future__ import annotations

from dataclasses import dataclass, field

from app.ml.types import ClientProfile


@dataclass
class AgentState:
    client_id: str
    doc_id: int
    profile: ClientProfile | None = None
    event: dict | None = None
    news_pool: dict[int, dict] = field(default_factory=dict)
    bank_pool: dict[int, dict] = field(default_factory=dict)
    plan: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def source_doc(self, chunk_id: int) -> int | None:
        c = self.news_pool.get(chunk_id) or self.bank_pool.get(chunk_id)
        return c["doc_id"] if c else None
