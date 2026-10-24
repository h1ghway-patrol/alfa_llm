from __future__ import annotations

import argparse
import json
import sys

from app.db import load_clients, load_counterparties, load_payments


def check_all(clients: str | None = None, payments: str | None = None,
              counterparties: str | None = None) -> dict[str, dict]:
    reports = {}
    if clients:
        reports["clients"] = load_clients.check_header(clients)
    if payments:
        reports["payments"] = load_payments.check_header(payments)
    if counterparties:
        reports["counterparties"] = load_counterparties.check_header(counterparties)
    return reports


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--clients")
    ap.add_argument("--payments")
    ap.add_argument("--counterparties")
    args = ap.parse_args(argv)
    reports = check_all(args.clients, args.payments, args.counterparties)
    if not reports:
        ap.error("укажите хотя бы один файл")
    bad = False
    for name, rep in reports.items():
        print(f"== {name} (разделитель {rep['delimiter']!r}, колонок: {len(rep['header'])})")
        if rep["missing"]:
            bad = True
            print("  НЕ НАЙДЕНЫ:", json.dumps(rep["missing"], ensure_ascii=False))
        else:
            print("  все колонки карты найдены")
        print("  не загружаются:", rep["unmapped"])
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
