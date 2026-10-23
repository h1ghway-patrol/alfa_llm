from __future__ import annotations

import csv
import difflib
import gzip


def sniff_delimiter(header_line: str) -> str:
    counts = {d: header_line.count(d) for d in (";", ",", "\t")}
    best = max(counts, key=counts.get)
    return best if counts[best] > 0 else ";"


def open_text(path):
    if str(path).endswith(".gz"):
        return gzip.open(path, "rt", encoding="utf-8-sig", newline="")
    return open(path, encoding="utf-8-sig", newline="")


def read_header(path) -> tuple[list[str], str]:
    with open_text(path) as f:
        line = f.readline()
    delim = sniff_delimiter(line)
    return [h.strip() for h in next(csv.reader([line], delimiter=delim))], delim


def check_columns(path, mapping: dict[str, str]) -> dict:
    header, delim = read_header(path)
    missing = {}
    for key, col in mapping.items():
        if col not in header:
            missing[key] = {"expected": col, "similar": difflib.get_close_matches(col, header, n=3, cutoff=0.4)}
    return {"header": header, "delimiter": delim, "missing": missing,
            "unmapped": [h for h in header if h not in mapping.values()]}
