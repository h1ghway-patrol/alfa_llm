from __future__ import annotations

import csv
import logging
import sqlite3
import statistics
from collections import Counter

log = logging.getLogger(__name__)

LARGE_THRESHOLD_RUB = 15_000_000_000         
DEMO_IDS = ["U_1465", "U_51606", "U_57706"]   

COLUMN_MAP = {
    "id": "SYNTHETIC_U_ID",                     
    "okved_code": "MAIN_OKVED",                 
    "okved_name": "MAIN_OKVED_NAME",          
    "city": "CITY_NAME",                       
    "region": "REGION_NAME",                  
    "revenue_rub": "REVENUE_COMPANY",           
    "ownership": "OKFS_NAME",                   
    "client_type": "CL_TYPE",                  
    "has_factoring": "FACTORING",               
    "has_fts": "FTS_FLAG",                     
    "fts_countries": "FTS_COUNTRY_NAME",        
    "group_id": "GROUP_ID",
    "key_owner_mark": "NEGATIVEMARK",
}

PRODUCT_MAP = {
    "has_loan":      "PRODUCT_CL_CREDIT",
    "has_leasing":   "PRODUCT_CL_LEASING",
    "has_guarantee": "PRODUCT_CL_GUARANTEE",
    "has_deposit":   "PRODUCT_CL_DEPOSIT",
    "has_rko":       "PRODUCT_CL_RKO",
    "has_payroll":   "PRODUCT_CL_PAYROLL",
}

FLAG_COLS = list(PRODUCT_MAP) + ["has_factoring", "has_fts"]

DB_COLUMNS = [
    "id", "okved_code", "okved_name", "city", "region", "revenue_rub",
    "ownership", "client_type",
    "has_loan", "has_leasing", "has_guarantee", "has_deposit",
    "has_rko", "has_payroll", "has_factoring", "has_fts", "fts_countries",
    "group_id", "key_owner_mark",
    "revenue_band", "group_size", "is_large", "is_demo",
]

def _clean(v: str | None) -> str | None:
    if v is None:
        return None
    v = v.strip()
    return v if v and v.lower() not in ("nan", "none", "null") else None


def _flag(v: str | None) -> int | None:
    v = _clean(v)
    if v is None:
        return None
    try:
        return 1 if float(v.replace(",", ".")) >= 0.5 else 0
    except ValueError:
        return None


def _num(v: str | None) -> float | None:
    v = _clean(v)
    if v is None:
        return None
    try:
        return float(v.replace(",", ".").replace(" ", ""))
    except ValueError:
        return None


def read_rows(csv_path: str) -> list[dict]:
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter=";")
        fields = reader.fieldnames or []

        needed = list(COLUMN_MAP.values()) + list(PRODUCT_MAP.values())
        missing = [c for c in needed if c not in fields]
        if missing:
            raise ValueError(
                "В CSV нет колонок: %s.\nЕсть: %s\n"
                "Исправьте COLUMN_MAP/PRODUCT_MAP в app/db/load_clients.py"
                % (missing, fields)
            )

        counts = Counter(fields)
        dupes = [c for c, n in counts.items() if n > 1 and c]
        if dupes:
            log.warning("В шапке CSV повторяются колонки: %s "
                        "(DictReader возьмёт последнюю)", dupes)

        return list(reader)


def revenue_band_edges(large_revenues: list[float]) -> list[float]:
    """Границы корзин по квартилям среди крупных (от 15 млрд до максимума)."""
    if len(large_revenues) < 4:
        return []
    return statistics.quantiles(large_revenues, n=4)


def revenue_band(rev: float | None, edges: list[float]) -> str | None:
    if rev is None:
        return None
    if rev <= LARGE_THRESHOLD_RUB:
        return "до 15 млрд"
    bounds = [LARGE_THRESHOLD_RUB] + edges
    for lo, hi in zip(bounds, bounds[1:]):
        if rev <= hi:
            return "%.0f–%.0f млрд" % (lo / 1e9, hi / 1e9)
    return "%.0f+ млрд" % (bounds[-1] / 1e9) if edges else "15+ млрд"


def load_clients(conn: sqlite3.Connection, csv_path: str, only_large: bool = True) -> dict:
    raw = read_rows(csv_path)
    log.info("Прочитано строк: %d", len(raw))
    counts = Counter(r[COLUMN_MAP["id"]].strip() for r in raw)
    dup_ids = {i for i, n in counts.items() if n > 1}
    rows = [r for r in raw if r[COLUMN_MAP["id"]].strip() not in dup_ids]
    log.warning("Дублирующихся ID: %d (удалено строк: %d)", len(dup_ids), len(raw) - len(rows))

    group_counts = Counter(_clean(r[COLUMN_MAP["group_id"]]) for r in rows if _clean(r[COLUMN_MAP["group_id"]]))
    if group_counts:
        log.info("Максимальный размер группы: %d (в описании данных: 624, сверьте)", max(group_counts.values()))

    parsed = []
    for r in rows:
        rec = {db: _clean(r[csv_col]) for db, csv_col in COLUMN_MAP.items()}
        rec["revenue_rub"] = _num(r[COLUMN_MAP["revenue_rub"]])
        for db_col, csv_col in PRODUCT_MAP.items():
            rec[db_col] = _flag(r[csv_col])
        rec["has_factoring"] = _flag(r[COLUMN_MAP["has_factoring"]])
        rec["has_fts"] = _flag(r[COLUMN_MAP["has_fts"]])
        rec["group_size"] = group_counts.get(rec["group_id"]) if rec["group_id"] else None
        rec["is_large"] = int(rec["revenue_rub"] is not None
                              and rec["revenue_rub"] > LARGE_THRESHOLD_RUB)
        parsed.append(rec)

    edges = revenue_band_edges([p["revenue_rub"] for p in parsed if p["is_large"]])
    for p in parsed:
        p["revenue_band"] = revenue_band(p["revenue_rub"], edges)
        p["is_demo"] = 0

    to_load = [p for p in parsed if p["is_large"]] if only_large else parsed
    ids = {p["id"] for p in to_load}
    missing_demo = [d for d in DEMO_IDS if d not in ids]
    if missing_demo:
        log.warning("Демо-клиенты не найдены среди загружаемых: %s", missing_demo)
    for p in to_load:
        p["is_demo"] = int(p["id"] in DEMO_IDS)


    cols = DB_COLUMNS
    sql = (
        "INSERT INTO company(%s) VALUES (%s) ON CONFLICT(id) DO UPDATE SET %s"
        % (", ".join(cols), ", ".join("?" * len(cols)),
           ", ".join("%s = excluded.%s" % (c, c) for c in cols if c != "id"))
    )
    with conn:
        conn.executemany(sql, [[p[c] for c in cols] for p in to_load])

    stats = {
        "rows_read": len(raw),
        "duplicate_ids": len(dup_ids),
        "loaded": len(to_load),
        "large": sum(p["is_large"] for p in parsed),
        "demo": sum(p["is_demo"] for p in to_load),
    }
    log.info("Итог загрузки клиентов: %s", stats)
    return stats