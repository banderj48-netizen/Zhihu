"""SQLite connection helpers for local development.

The rest of the application should use repositories rather than importing this
module directly. A PostgreSQL implementation can keep the same repository
contracts later.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterator


BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE_PATH = BACKEND_ROOT / "data" / "twinloop.db"
SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def connect(database_path: str | Path = DEFAULT_DATABASE_PATH) -> sqlite3.Connection:
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    return connection


def initialize(database_path: str | Path = DEFAULT_DATABASE_PATH) -> Path:
    path = Path(database_path)
    with connect(path) as connection:
        connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        connection.execute(
            "INSERT INTO schema_meta(key, value, updated_at) VALUES (?, ?, datetime('now')) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            ("schema_version", "1"),
        )
    return path


def connection(database_path: str | Path = DEFAULT_DATABASE_PATH) -> Iterator[sqlite3.Connection]:
    db = connect(database_path)
    try:
        yield db
    finally:
        db.close()
