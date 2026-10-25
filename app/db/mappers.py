from __future__ import annotations

from app.db.ids import to_str_id

FLAGS = ["has_loan", "has_leasing", "has_guarantee", "has_deposit", "has_rko",
         "has_payroll", "has_factoring", "has_fts"]

PRODUCT_LABELS = {"has_loan": "кредит", "has_leasing": "лизинг", "has_guarantee": "гарантии",
                  "has_deposit": "депозит", "has_rko": "РКО", "has_payroll": "зарплатный проект",
                  "has_factoring": "факторинг"}

PRODUCT_CODES = {
    "has_loan": "loan",
    "has_leasing": "leasing",
    "has_guarantee": "guarantee",
    "has_deposit": "deposit",
    "has_rko": "rko",
    "has_payroll": "payroll",
    "has_factoring": "factoring",
}

TAG_CODES = {
    "fuel_trade": "industry",
    "construction": "industry",
    "wholesale": "industry",
    "real_estate": "industry",
    "it": "industry",
    "logistics": "industry",
    "energy": "industry",
    "debt_sensitive": "debt_sensitivity",
    "fx_exposed": "currency_dependency",
    "group_member": "group_position",
    "large_scale": "scale",
}


def _bool(v) -> bool | None:
    return None if v is None else bool(v)


def products_of(row: dict) -> list[str]:
    return [code for key, code in PRODUCT_CODES.items() if row.get(key) == 1]


def _tag_of(tag: dict) -> dict | None:
    """Приводит тег ML-профиля к контракту `ClientTag`.

    ML-слой называет теги по-своему (`debt_sensitive`, `fuel_trade`), а API
    ждёт фиксированные коды. Уже готовый тег возвращается без изменений.
    """
    if "code" in tag:
        return {
            "code": tag["code"],
            "label": tag.get("label", ""),
            "evidence": list(tag.get("evidence") or []),
        }
    name = tag.get("name")
    code = TAG_CODES.get(name)
    if code is None:
        return None
    return {
        "code": code,
        "label": tag.get("label", ""),
        "evidence": list(tag.get("evidence") or []),
    }


def countries_of(row: dict) -> list[str]:
    raw = row.get("fts_countries") or ""
    return [c.strip() for c in raw.split(",") if c.strip()]


_CLIENT_TYPES = {
    "client": "CLIENT",
    "корпоративный": "CLIENT",
    "prospect": "PROSPECT",
    "потенциальный": "PROSPECT",
    "close_client": "CLOSE_CLIENT",
    "закрытый": "CLOSE_CLIENT",
}


def _client_type(value: str | None) -> str | None:
    if value is None:
        return None
    return _CLIENT_TYPES.get(value.strip().lower())


def to_client_summary(row: dict) -> dict:
    return {
        "client_id": row["id"],
        "industry": row.get("okved_name"),
        "okved_code": row.get("okved_code"),
        "okved_name": row.get("okved_name"),
        "city": row.get("city"),
        "region": row.get("region"),
        "revenue_band": row.get("revenue_band"),
        "employees_band": row.get("employees_band"),
        "age_band": row.get("age_band"),
        "group_id": row.get("group_id"),
        "group_size": row.get("group_size"),
        "is_large": bool(row.get("is_large")),
        "is_demo": bool(row.get("is_demo")),
        "products": products_of(row),
    }


def to_client_profile(row: dict, tags: list[dict] | None = None) -> dict:
    out = to_client_summary(row)
    normalized_tags = [t for t in (_tag_of(tag) for tag in (tags or [])) if t is not None]
    out.update({
        "revenue_rub": row.get("revenue_rub"),
        "ownership": row.get("ownership"),
        "business_stage": row.get("business_stage"),
        "client_type": _client_type(row.get("client_type")),
        "fts_countries": countries_of(row),
        "key_owner_mark": _bool(row.get("key_owner_mark")),
        "unknown_features": [k for k in FLAGS if row.get(k) is None],
        "tags": normalized_tags,
    })
    for key in FLAGS:
        out[key] = _bool(row.get(key))
    return out


def to_feed_item(row: dict) -> dict:
    return {
        "event_id": to_str_id(row["event_id"]),
        "title": row["title"],
        "published_at": row.get("published_at"),
        "source_name": row.get("source_name"),
        "topics": list(row.get("topics") or []),
        "relevance_score": row["relevance_score"],
        "relevance_reasons": list(row.get("relevance_reasons") or [])[:3],
        "has_insight": bool(row.get("has_insight")),
    }


def to_event(row: dict) -> dict:
    return {
        "event_id": to_str_id(row["id"]),
        "title": row["title"],
        "published_at": row.get("doc_date"),
        "source_name": row.get("source_name"),
        "url": row.get("url"),
        "topics": list(row.get("topics") or []),
        "facts": row.get("facts"),
        "freshness": row.get("status"),
    }


def to_source_fragment(row: dict) -> dict:
    return {
        "source_id": to_str_id(row["source_id"]),
        "doc_title": row["doc_title"],
        "doc_kind": row["doc_kind"],
        "doc_date": row.get("doc_date"),
        "section_path": row.get("section_path"),
        "text": row["text"],
        "url": row.get("url"),
        "freshness": row["freshness"],
    }


def to_run(row: dict) -> dict:
    return {
        "run_id": to_str_id(row["id"]),
        "status": row["status"],
        "insight_id": to_str_id(row.get("insight_id")),
        "error": row.get("error"),
    }


def _claim(c: dict) -> dict:
    out = {"text": c["text"], "kind": c["kind"], "source_ids": [str(i) for i in c.get("source_ids") or []]}
    if c.get("client_features"):
        out["client_features"] = list(c["client_features"])
    return out


def _claims(items) -> list[dict]:
    return [_claim(c) for c in items or []]


def to_insight(row: dict) -> dict:
    body = row["body"]
    cons = body.get("consequences") or {}
    return {
        "insight_id": to_str_id(row["id"]),
        "client_id": row["client_id"],
        "event_id": to_str_id(row["doc_id"]),
        "status": row["status"],
        "created_at": row["created_at"],
        "what_happened": _claims(body.get("what_happened")),
        "why_it_matters": _claims(body.get("why_it_matters")),
        "consequences": {"risks": _claims(cons.get("risks")), "opportunities": _claims(cons.get("opportunities"))},
        "actions": _claims(body.get("actions")),
        "bank_view": _claims(body.get("bank_view")),
        "basis": _claims(body.get("basis")),
        "data_quality_notes": list(body.get("data_quality_notes") or []),
    }


def to_trace_step(row: dict) -> dict:
    return {
        "step_no": row["step_no"],
        "step_type": row["step_type"],
        "tool_name": row.get("tool_name"),
        "input": row.get("input"),
        "output": row.get("output"),
        "model": row.get("model"),
        "tokens_in": row.get("tokens_in", 0),
        "tokens_out": row.get("tokens_out", 0),
        "latency_ms": row.get("latency_ms"),
        "created_at": row.get("created_at"),
    }
