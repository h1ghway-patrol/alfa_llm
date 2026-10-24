from __future__ import annotations

import re

_ID = re.compile(r"[0-9]{1,18}")


class InvalidId(ValueError):
    pass


def parse_id(raw) -> int:
    if isinstance(raw, int) and not isinstance(raw, bool) and raw >= 0:
        return raw
    if isinstance(raw, str) and _ID.fullmatch(raw):
        return int(raw)
    raise InvalidId(f"Некорректный идентификатор: {raw!r}")


def to_str_id(value) -> str | None:
    return None if value is None else str(value)
