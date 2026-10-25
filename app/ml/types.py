from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator

CLAIM_KINDS = ("fact", "bank", "ai", "client")
MAX_CLAIM_CHARS = 500
MAX_CLAIMS_PER_BLOCK = 6


@dataclass
class Tag:
    name: str
    label: str
    evidence: list[str]

    def to_dict(self) -> dict:
        return {"name": self.name, "label": self.label, "evidence": list(self.evidence)}


@dataclass
class ClientProfile:
    client_id: str
    features: dict
    tags: list[Tag] = field(default_factory=list)
    products: list[str] = field(default_factory=list)
    unknown_features: list[str] = field(default_factory=list)

    def tag(self, name: str) -> Tag | None:
        return next((t for t in self.tags if t.name == name), None)

    def tag_names(self) -> set[str]:
        return {t.name for t in self.tags}

    def feature_refs(self) -> list[str]:
        refs = [t.name for t in self.tags]
        refs += [k for k, v in self.features.items() if v is not None and k != "id"]
        return list(dict.fromkeys(refs))

    def to_llm_view(self) -> dict:
        f = self.features
        return {"client_id": self.client_id, "industry": f.get("okved_name"), "region": f.get("region"),
                "revenue_band": f.get("revenue_band"), "employees_band": f.get("employees_band"),
                "products": self.products, "tags": [t.to_dict() for t in self.tags]}

    def to_dict(self) -> dict:
        return {**self.to_llm_view(), "features": self.features, "unknown_features": self.unknown_features}


@dataclass
class Claim:
    text: str
    kind: str
    source_ids: list[int] = field(default_factory=list)
    client_features: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d) -> "Claim":
        if not isinstance(d, dict):
            raise ValueError(f"claim должен быть объектом, получено {type(d).__name__}")
        text, kind = d.get("text"), d.get("kind")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("claim.text пуст")
        if len(text) > MAX_CLAIM_CHARS:
            raise ValueError(f"claim.text длиннее {MAX_CLAIM_CHARS} символов")
        if kind not in CLAIM_KINDS:
            raise ValueError(f"claim.kind должен быть одним из {CLAIM_KINDS}, получено {kind!r}")
        ids = d.get("source_ids", [])
        if not isinstance(ids, list) or not all(isinstance(i, int) and not isinstance(i, bool) for i in ids):
            raise ValueError("claim.source_ids должен быть списком целых чисел")
        feats = d.get("client_features", [])
        if not isinstance(feats, list) or not all(isinstance(x, str) for x in feats):
            raise ValueError("claim.client_features должен быть списком строк")
        return cls(text.strip(), kind, list(ids), list(feats))

    def to_dict(self) -> dict:
        d = {"text": self.text, "kind": self.kind, "source_ids": list(self.source_ids)}
        if self.client_features:
            d["client_features"] = list(self.client_features)
        return d


_FLAT = ("what_happened", "why_it_matters", "actions", "bank_view", "basis")


@dataclass
class Insight:
    what_happened: list[Claim] = field(default_factory=list)
    why_it_matters: list[Claim] = field(default_factory=list)
    risks: list[Claim] = field(default_factory=list)
    opportunities: list[Claim] = field(default_factory=list)
    actions: list[Claim] = field(default_factory=list)
    bank_view: list[Claim] = field(default_factory=list)
    basis: list[Claim] = field(default_factory=list)
    data_quality_notes: list[str] = field(default_factory=list)

    def blocks(self) -> dict[str, list[Claim]]:
        return {"what_happened": self.what_happened, "why_it_matters": self.why_it_matters,
                "consequences.risks": self.risks, "consequences.opportunities": self.opportunities,
                "actions": self.actions, "bank_view": self.bank_view, "basis": self.basis}

    def iter_claims(self) -> Iterator[tuple[str, int, Claim]]:
        for key, claims in self.blocks().items():
            for i, c in enumerate(claims):
                yield key, i, c

    @classmethod
    def from_dict(cls, d) -> "Insight":
        if not isinstance(d, dict):
            raise ValueError("инсайт должен быть JSON-объектом")
        missing = [k for k in (*_FLAT, "consequences") if k not in d]
        if missing:
            raise ValueError(f"нет блоков: {missing}")
        cons = d["consequences"]
        if not isinstance(cons, dict) or "risks" not in cons or "opportunities" not in cons:
            raise ValueError("consequences должен содержать risks и opportunities")

        def claims(key, raw):
            if not isinstance(raw, list):
                raise ValueError(f"{key} должен быть списком")
            if len(raw) > MAX_CLAIMS_PER_BLOCK:
                raise ValueError(f"в блоке {key} больше {MAX_CLAIMS_PER_BLOCK} утверждений")
            return [Claim.from_dict(x) for x in raw]

        notes = d.get("data_quality_notes", [])
        if not isinstance(notes, list) or not all(isinstance(n, str) for n in notes):
            raise ValueError("data_quality_notes должен быть списком строк")
        return cls(
            what_happened=claims("what_happened", d["what_happened"]),
            why_it_matters=claims("why_it_matters", d["why_it_matters"]),
            risks=claims("consequences.risks", cons["risks"]),
            opportunities=claims("consequences.opportunities", cons["opportunities"]),
            actions=claims("actions", d["actions"]),
            bank_view=claims("bank_view", d["bank_view"]),
            basis=claims("basis", d["basis"]),
            data_quality_notes=list(notes),
        )

    def to_dict(self) -> dict:
        cl = lambda xs: [c.to_dict() for c in xs]
        return {"what_happened": cl(self.what_happened), "why_it_matters": cl(self.why_it_matters),
                "consequences": {"risks": cl(self.risks), "opportunities": cl(self.opportunities)},
                "actions": cl(self.actions), "bank_view": cl(self.bank_view), "basis": cl(self.basis),
                "data_quality_notes": list(self.data_quality_notes)}
