from __future__ import annotations

import csv
import logging
import sqlite3

from app.db.csvutil import check_columns, open_text, sniff_delimiter

log = logging.getLogger(__name__)

PAYMENT_COLUMNS = {"payer": "PAYER", "beneficiary": "BENEFICIARY", "amount_rub": "PAY_AMT", "cnt": "PAY_CNT"}


def check_header(path: str) -> dict:
    return check_columns(path, PAYMENT_COLUMNS)


def load_payments(conn: sqlite3.Connection, path: str, delimiter: str | None = None) -> dict:
    client_ids = {r["id"] for r in conn.execute("SELECT id FROM company")}
    agg: dict[tuple[str, str], list[float]] = {}
    total = self_pay = bad_rows = 0
    with open_text(path) as f:
        delim = delimiter or sniff_delimiter(f.readline())
        f.seek(0)
        reader = csv.DictReader(f, delimiter=delim)
        missing = [c for c in PAYMENT_COLUMNS.values() if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError("В файле платежей нет колонок %s; есть %s" % (missing, reader.fieldnames))
        c_pay, c_ben, c_amt, c_cnt = (PAYMENT_COLUMNS[k] for k in ("payer", "beneficiary", "amount_rub", "cnt"))
        for row in reader:
            total += 1
            payer, ben = (row[c_pay] or "").strip(), (row[c_ben] or "").strip()
            if not payer or not ben:
                bad_rows += 1
                continue
            if payer == ben:
                self_pay += 1
                continue
            if payer not in client_ids and ben not in client_ids:
                continue
            try:
                amount = float(row[c_amt].replace(",", "."))
                cnt = int(float(row[c_cnt] or 1))
            except (ValueError, AttributeError):
                bad_rows += 1
                continue
            acc = agg.setdefault((payer, ben), [0.0, 0])
            acc[0] += amount
            acc[1] += cnt

    with conn:
        conn.execute("DELETE FROM payment")
        conn.executemany(
            "INSERT INTO payment(payer, beneficiary, amount_rub, cnt) VALUES (?,?,?,?)",
            [(p, b, a, c) for (p, b), (a, c) in agg.items()],
        )
    top = conn.execute(
        "SELECT payer, beneficiary, amount_rub FROM payment ORDER BY amount_rub DESC LIMIT 3"
    ).fetchall()
    stats = {"rows_read": total, "self_payments_skipped": self_pay, "bad_rows": bad_rows,
             "edges_kept": len(agg), "top_amounts": [dict(r) for r in top]}
    log.info("Итог загрузки платежей: %s (проверьте выброс ~1,1 трлн ₽)", stats)
    return stats
