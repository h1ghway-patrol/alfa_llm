from __future__ import annotations

import csv
import logging
import sqlite3
from collections import defaultdict

from app.db.csvutil import check_columns, open_text, sniff_delimiter

log = logging.getLogger(__name__)

GEO_COLUMNS = {"f_id": "SYNTHETIC_F", "city_name": "CITY_NAME", "region_name": "RC_NAME", "client_id": "SYNTHETIC_U"}


def check_header(path: str) -> dict:
    return check_columns(path, GEO_COLUMNS)


def _clean(v: str | None) -> str | None:
    v = (v or "").strip()
    return v if v and v.lower() not in ("nan", "none", "null") else None


def load_counterparties(conn: sqlite3.Connection, path: str, only_relevant: bool = True) -> dict:
    relevant: set[str] = set()
    if only_relevant:
        relevant = {r[0] for r in conn.execute(
            "SELECT payer FROM payment UNION SELECT beneficiary FROM payment UNION SELECT id FROM company")}
        if not relevant:
            log.warning("Нет ни клиентов, ни платежей: фильтр по связанности отключён, грузим всё")

    rows: dict[tuple[str, str], tuple] = {}
    total = empty_f = filtered = 0
    with open_text(path) as f:
        delim = sniff_delimiter(f.readline())
        f.seek(0)
        reader = csv.DictReader(f, delimiter=delim)
        missing = [c for c in GEO_COLUMNS.values() if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError("В файле контрагентов нет колонок %s; есть %s. Исправьте GEO_COLUMNS в "
                             "app/db/load_counterparties.py" % (missing, reader.fieldnames))
        for r in reader:
            total += 1
            f_id, u = _clean(r[GEO_COLUMNS["f_id"]]), _clean(r[GEO_COLUMNS["client_id"]])
            if f_id is None:
                empty_f += 1
                continue
            if relevant and f_id not in relevant and (u is None or u not in relevant):
                filtered += 1
                continue
            rows[(f_id, u or "")] = (f_id, u, _clean(r[GEO_COLUMNS["city_name"]]),
                                     _clean(r[GEO_COLUMNS["region_name"]]))

    clients_per_f: dict[str, set] = defaultdict(set)
    for f_id, u in rows:
        if u:
            clients_per_f[f_id].add(u)
    with conn:
        conn.execute("DELETE FROM counterparty")
        conn.executemany("INSERT INTO counterparty(f_id, client_id, city_name, region_name) VALUES (?,?,?,?)",
                         list(rows.values()))
    stats = {"rows_read": total, "kept": len(rows), "empty_f_skipped": empty_f, "filtered_out": filtered,
             "distinct_f": len({k[0] for k in rows}),
             "f_with_several_clients": sum(1 for v in clients_per_f.values() if len(v) > 1),
             "rows_without_client": sum(1 for v in rows.values() if v[1] is None)}
    if stats["f_with_several_clients"]:
        log.warning("%d контрагентов связаны с несколькими клиентами: проверьте смысл SYNTHETIC_U",
                    stats["f_with_several_clients"])
    log.info("Итог загрузки контрагентов: %s", stats)
    return stats
