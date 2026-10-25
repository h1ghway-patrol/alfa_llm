from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Iterator

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def default_db_path() -> str:
    return os.environ.get("DB_PATH", "data/app.db")


def connect(db_path: str | os.PathLike | None = None) -> sqlite3.Connection:
    path = str(db_path or default_db_path())
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    if path != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def check_fts5() -> None:
    c = sqlite3.connect(":memory:")
    try:
        c.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
    except sqlite3.OperationalError as e:
        raise RuntimeError(
            "В этой сборке SQLite нет FTS5 (sqlite %s). Нужна другая сборка Python/SQLite."
            % sqlite3.sqlite_version
        ) from e
    finally:
        c.close()


def init_db(conn: sqlite3.Connection) -> None:
    check_fts5()
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.commit()


def verify_db(db_path: str | os.PathLike) -> None:
    """Проверяет, что файл БД существует и схема приложения создана."""
    path = Path(db_path)
    if not path.is_file():
        raise RuntimeError(
            f"USE_DB=true, но файл БД {path} не найден. "
            "Соберите её командой: python -m app.db.build --db ..."
        )
    conn = connect(path)
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'company'"
        ).fetchone()
        if row is None:
            raise RuntimeError(f"В БД {path} нет схемы приложения. Пересоберите её с --rebuild.")
    finally:
        conn.close()


def get_db() -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()
