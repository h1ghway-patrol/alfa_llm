from __future__ import annotations

import csv
import logging
import sqlite3
import statistics
from collections import Counter

from app.db.csvutil import check_columns, sniff_delimiter

log = logging.getLogger(__name__)

LARGE_THRESHOLD_RUB = 15_000_000_000
DEMO_IDS = ["U_1465", "U_51606", "U_57706"]

COLUMN_MAP = {
    "id": "SYNTHETIC_U",
    "okved_code": "MAINOKVED_CODE",
    "okved_name": "MAINOKVED_NAME",
    "city": "CITY",
    "region": "REGION",
    "revenue_rub": "REVENUE_COMPANY",
    "employees_band": "AMOUNT_WORKERS_FNS_GRADATION",
    "age_band": "COMPANY_AGE_YEARS_GRADATION",
    "ownership": "OKFS_NAME",
    "business_stage": "ECO_MARK_LABEL",
    "client_type": "CL_TYPE",
    "has_loan": "CL_PRODUCT_LOA_MARK",
    "has_leasing": "CL_PRODUCT_LEA_MARK",
    "has_guarantee": "CL_PRODUCT_GAR_MARK",
    "has_deposit": "CL_PRODUCT_DEP_MARK",
    "has_rko": "CL_PRODUCT_RKO_MARK",
    "has_payroll": "CL_PRODUCT_ZPP_MARK",
    "has_factoring": "FACTORING_MARK",
    "has_fts": "FTS_FLAG",
    "fts_countries": "FTS_COUNTRY_NAME",
    "group_id": "GROUP_ID",
    "key_owner_mark": "NEGATIVEMARK",
}

FLAG_COLS = ["has_loan", "has_leasing", "has_guarantee", "has_deposit", "has_rko",
             "has_payroll", "has_factoring", "has_fts", "key_owner_mark"]

DB_COLUMNS = list(COLUMN_MAP) + ["revenue_band", "group_size", "is_large", "is_demo"]


def _clean(v: str | None) -> str | None:
    if v is None:
        return None
    v = v.strip()
    return v if v and v.lower() not in ("nan", "none", "null") else None


_TRUE = {"да", "yes", "true", "y", "t"}
_FALSE = {"нет", "no", "false", "n", "f"}
_UNPARSED: Counter = Counter()


def _flag(v: str | None, col: str = "?") -> int | None:
    v = _clean(v)
    if v is None:
        return None
    low = v.lower()
    if low in _TRUE:
        return 1
    if low in _FALSE:
        return 0
    try:
        return 1 if float(v.replace(",", ".")) >= 0.5 else 0
    except ValueError:
        _UNPARSED[col] += 1
        return None


def _num(v: str | None) -> float | None:
    v = _clean(v)
    if v is None:
        return None
    try:
        return float(v.replace(",", ".").replace(" ", ""))
    except ValueError:
        return None


def check_header(csv_path: str) -> dict:
    return check_columns(csv_path, COLUMN_MAP)


def read_rows(csv_path: str) -> list[dict]:
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        delim = sniff_delimiter(f.readline())
        f.seek(0)
        reader = csv.DictReader(f, delimiter=delim)
        missing = [c for c in COLUMN_MAP.values() if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(
                "В CSV нет колонок: %s.\nЕсть: %s\nИсправьте COLUMN_MAP в app/db/load_clients.py"
                % (missing, reader.fieldnames)
            )
        return list(reader)


def revenue_band_edges(large_revenues: list[float]) -> list[float]:
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
    _UNPARSED.clear()
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
        rec["id"] = rec["id"]
        rec["revenue_rub"] = _num(r[COLUMN_MAP["revenue_rub"]])
        for c in FLAG_COLS:
            rec[c] = _flag(r[COLUMN_MAP[c]], c)
        rec["group_size"] = group_counts.get(rec["group_id"]) if rec["group_id"] else None
        rec["is_large"] = int(rec["revenue_rub"] is not None and rec["revenue_rub"] > LARGE_THRESHOLD_RUB)
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
    if _UNPARSED:
        stats["unparsed_flags"] = dict(_UNPARSED)
        log.warning("Не распознаны значения флагов (сохранены как NULL): %s", dict(_UNPARSED))
    log.info("Итог загрузки клиентов: %s", stats)
    return stats


if __name__ == "__main__":
    import json
    import sys
    rep = check_header(sys.argv[1])
    print("Не найдены колонки COLUMN_MAP:" if rep["missing"] else "Все колонки COLUMN_MAP найдены.")
    print(json.dumps(rep["missing"], ensure_ascii=False, indent=2))
    print("Колонки CSV, которые не загружаются:", rep["unmapped"])
    sys.exit(1 if rep["missing"] else 0)
