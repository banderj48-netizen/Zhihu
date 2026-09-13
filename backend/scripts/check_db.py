"""Check the PostgreSQL schema status."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import psycopg

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from db.database import connect  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Check the TwinLoop PostgreSQL database")
    parser.add_argument("--url", help="PostgreSQL URL; defaults to DATABASE_URL or backend/.env")
    args = parser.parse_args()
    try:
        with connect(args.url) as db:
            version = db.execute("SELECT version FROM schema_migrations ORDER BY version DESC LIMIT 1").fetchone()
            tables = db.execute("SELECT tablename FROM pg_tables WHERE schemaname = current_schema() ORDER BY tablename").fetchall()
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except psycopg.Error:
        print("PostgreSQL check failed; verify connection settings and run init_db.py first.", file=sys.stderr)
        return 1
    print(f"schema_version: {version['version'] if version else 'missing'}")
    print(f"tables: {len(tables)}")
    for table in tables:
        print(f"- {table['tablename']}")
    return 0 if version else 1


if __name__ == "__main__":
    raise SystemExit(main())
