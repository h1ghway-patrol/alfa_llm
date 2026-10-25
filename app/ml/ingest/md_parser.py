from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

RU_MONTHS = {"января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5, "июня": 6, "июля": 7,
             "августа": 8, "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12}
MAX_CHUNK_CHARS = 1500

_META = re.compile(r"^\s*[*_>\-\s]*(Дата|Источник|Ссылка|URL)\s*[*_]*\s*:\s*[*_]*\s*(.+?)[*_\s]*$", re.I)
_H = re.compile(r"^(#{1,3})\s+(.*\S)\s*$")


def parse_date(s: str | None) -> str | None:
    if not s:
        return None
    s = s.strip().lower()
    try:
        if m := re.search(r"(\d{4})-(\d{2})-(\d{2})", s):
            return date(int(m[1]), int(m[2]), int(m[3])).isoformat()
        if m := re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", s):
            return date(int(m[3]), int(m[2]), int(m[1])).isoformat()
        if m := re.search(r"(\d{1,2})\s+([а-я]+)\s+(\d{4})", s):
            if m[2] in RU_MONTHS:
                return date(int(m[3]), RU_MONTHS[m[2]], int(m[1])).isoformat()
    except ValueError:
        return None
    return None


@dataclass
class ParsedDoc:
    title: str | None = None
    date: str | None = None
    source: str | None = None
    url: str | None = None
    sections: list[tuple[str, str, str]] = field(default_factory=list)


def parse_md(text: str) -> ParsedDoc:
    doc = ParsedDoc()
    h2 = h3 = None
    heading = None
    path = None
    body: list[str] = []
    seen_h2 = False

    def flush():
        txt = "\n".join(body).strip()
        if txt and path:
            doc.sections.append((path, heading or path, txt))

    for line in text.splitlines():
        m = _H.match(line)
        if m and len(m[1]) == 1 and doc.title is None:
            doc.title = m[2].strip()
            path, heading = doc.title, doc.title
            continue
        if m and len(m[1]) in (2, 3):
            flush()
            body = []
            seen_h2 = True
            if len(m[1]) == 2:
                h2, h3 = m[2], None
            else:
                h3 = m[2]
            path = " > ".join(x for x in (h2, h3) if x)
            heading = h3 or h2
            continue
        if not seen_h2 and (mm := _META.match(line)):
            key, val = mm[1].lower(), mm[2].strip()
            if key == "дата":
                doc.date = parse_date(val)
            elif key == "источник":
                doc.source = val
            else:
                doc.url = val
            continue
        body.append(line)
    flush()
    return doc


def _blocks(body: str) -> list[str]:
    blocks, cur, cur_table = [], [], False
    for line in body.splitlines():
        if not line.strip():
            if cur:
                blocks.append("\n".join(cur))
                cur = []
            continue
        is_table = line.lstrip().startswith("|")
        if cur and is_table != cur_table:
            blocks.append("\n".join(cur))
            cur = []
        cur.append(line)
        cur_table = is_table
    if cur:
        blocks.append("\n".join(cur))
    return blocks


def pack_chunks(body: str, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    out, cur = [], ""
    for b in _blocks(body):
        if cur and len(cur) + len(b) + 2 > max_chars:
            out.append(cur)
            cur = ""
        cur = f"{cur}\n\n{b}" if cur else b
    if cur:
        out.append(cur)
    return [c.strip() for c in out if c.strip()]


def to_chunks(doc: ParsedDoc, max_chars: int = MAX_CHUNK_CHARS) -> list[dict]:
    chunks = []
    for path, heading, body in doc.sections:
        for piece in pack_chunks(body, max_chars):
            chunks.append({"section_path": path, "text": f"{heading}\n{piece}"})
    return chunks
