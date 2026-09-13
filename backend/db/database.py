"""PostgreSQL-only connections and transactional, versioned migrations."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Iterator
from urllib.parse import urlsplit

import psycopg
from dotenv import dotenv_values
from psycopg.rows import dict_row

BACKEND_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = Path(__file__).with_name("schema.sql")
MIGRATIONS_PATH = Path(__file__).with_name("migrations")
SCHEMA_VERSION = 2
MIGRATION_LOCK = 716052809


def database_url(url: str | None = None) -> str:
    if url is None:
        url = os.getenv("DATABASE_URL")
        if url is None:
            url = dotenv_values(BACKEND_ROOT / ".env").get("DATABASE_URL")
    if not isinstance(url, str) or not url.strip():
        raise ValueError("Set DATABASE_URL to a PostgreSQL URL in the environment or backend/.env")
    value = url.strip()
    try:
        parsed = urlsplit(value)
        valid = parsed.scheme in {"postgresql", "postgres"} and bool(parsed.hostname) and parsed.path not in {"", "/"} and not parsed.fragment
        _ = parsed.port
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("Only postgresql:// or postgres:// database URLs are supported")
    return value


def connect(url: str | None = None) -> psycopg.Connection:
    return psycopg.connect(database_url(url), row_factory=dict_row, connect_timeout=5, application_name="twinloop")


def migration_files() -> list[tuple[int, Path]]:
    return [(1, SCHEMA_PATH), (2, MIGRATIONS_PATH / "002_personality_assessment.sql")]


def initialize(url: str | None = None) -> int:
    """Apply each migration once with a PostgreSQL advisory transaction lock."""
    with connect(url) as db:
        db.execute("SELECT pg_advisory_xact_lock(%s)", (MIGRATION_LOCK,))
        db.execute("""CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            checksum TEXT NOT NULL,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        applied = {row["version"]: row for row in db.execute("SELECT * FROM schema_migrations")}
        if applied and max(applied) > SCHEMA_VERSION:
            raise RuntimeError("Database schema is newer than this application")
        for version, path in migration_files():
            source = path.read_text(encoding="utf-8")
            checksum = hashlib.sha256(source.encode("utf-8")).hexdigest()
            if version in applied:
                if applied[version]["checksum"] != checksum:
                    raise RuntimeError(f"Applied migration {version} changed; add a new migration instead")
                continue
            db.execute(source)
            db.execute("INSERT INTO schema_migrations(version, name, checksum) VALUES (%s, %s, %s)", (version, path.name, checksum))
        db.execute("""INSERT INTO schema_meta(key, value, updated_at)
            VALUES ('schema_version', %s, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value, updated_at=EXCLUDED.updated_at""", (str(SCHEMA_VERSION),))
    return SCHEMA_VERSION


def connection(url: str | None = None) -> Iterator[psycopg.Connection]:
    with connect(url) as db:
        yield db
