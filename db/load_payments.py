from __future__ import annotations

import csv
import gzip
import logging
import sqlite3

log = logging.getLogger(__name__)

PAYMENT_COLUMNS = {
    "payer": "PAYER",
    "beneficiary": "BENEFICIARY",
    "amount_rub": "PAY_AMT",   
    "cnt": "PAY_CNT",         
}


def load_payments(conn: sqlite3.Connection, path: str, delimiter: str = ";") -> dict:
    client_ids = {r["id"] for r in conn.execute("SELECT id FROM company")}
    opener = gzip.open if str(path).endswith(".gz") else open
    agg: dict[tuple[str, str], list[float]] = {}
    total = self_pay = 0
    with opener(path, "rt", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter=delimiter)
        missing = [c for c in PAYMENT_COLUMNS.values() if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError("В файле платежей нет колонок %s; есть %s" % (missing, reader.fieldnames))
        c_pay, c_ben, c_amt, c_cnt = (PAYMENT_COLUMNS[k] for k in ("payer", "beneficiary", "amount_rub", "cnt"))
        for row in reader:                     
            total += 1
            payer, ben = row[c_pay].strip(), row[c_ben].strip()
            if payer == ben:
                self_pay += 1
                continue
            if payer not in client_ids and ben not in client_ids:
                continue                        
            try:
                amount = float(row[c_amt].replace(",", "."))
                cnt = int(float(row[c_cnt] or 1))
            except ValueError:
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
    stats = {"rows_read": total, "self_payments_skipped": self_pay, "edges_kept": len(agg),
             "top_amounts": [dict(r) for r in top]}
    log.info("Итог загрузки платежей: %s (проверьте выброс ~1,1 трлн ₽)", stats)
    return stats