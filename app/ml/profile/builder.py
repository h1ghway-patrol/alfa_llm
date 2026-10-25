from __future__ import annotations

import sqlite3

from app.db import repositories as repo
from app.db.mappers import FLAGS, PRODUCT_LABELS
from app.ml.config import load_config
from app.ml.types import ClientProfile, Tag

DEBT_PRODUCTS = ("has_loan", "has_leasing", "has_guarantee")
_HIDDEN = {"key_owner_mark", "is_demo"}


def match_okved(code: str | None) -> dict | None:
    if not code:
        return None
    digits = code.replace(".", "").strip()
    best, best_len = None, 0
    for rule in load_config("okved_map.yaml")["rules"]:
        for p in rule["prefixes"]:
            pd = p.replace(".", "")
            if digits.startswith(pd) and len(pd) > best_len:
                best, best_len = rule, len(pd)
    return best


def build_profile(conn: sqlite3.Connection, client_id: str) -> ClientProfile:
    row = repo.get_client(conn, client_id)
    if row is None:
        raise KeyError(f"Клиент {client_id!r} не найден")
    f = {k: v for k, v in row.items() if k not in _HIDDEN}
    tags: list[Tag] = []

    rule = match_okved(f.get("okved_code"))
    if rule:
        tags.append(Tag(rule["tag"], rule["label"],
                        [f"ОКВЭД {f['okved_code']}" + (f" — {f['okved_name']}" if f.get("okved_name") else "")]))

    debt = [f"Есть продукт банка: {PRODUCT_LABELS[k]}" for k in DEBT_PRODUCTS if f.get(k) == 1]
    if debt:
        tags.append(Tag("debt_sensitive", "Чувствителен к стоимости долга", debt))

    if f.get("has_fts") == 1:
        ev = "Участвует во внешнеэкономической деятельности"
        if f.get("fts_countries"):
            ev += f", страны: {f['fts_countries']}"
        tags.append(Tag("fx_exposed", "Валютная зависимость (ВЭД)", [ev]))

    if f.get("group_size") and f["group_size"] > 1:
        tags.append(Tag("group_member", "Входит в группу компаний",
                        [f"Группа {f.get('group_id')}: {f['group_size']} компаний в базе"]))

    if f.get("is_large"):
        ev = [f"Выручка {f['revenue_rub'] / 1e9:.1f} млрд ₽" + (f" ({f['revenue_band']})" if f.get("revenue_band") else "")
              ] if f.get("revenue_rub") else ["Крупный клиент"]
        if f.get("employees_band"):
            ev.append(f"Численность: {f['employees_band']}")
        tags.append(Tag("large_scale", "Крупный бизнес", ev))

    return ClientProfile(
        client_id=client_id, features=f, tags=tags,
        products=[PRODUCT_LABELS[k] for k in PRODUCT_LABELS if f.get(k) == 1],
        unknown_features=[k for k in FLAGS if f.get(k) is None],
    )
