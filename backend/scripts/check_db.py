"""Print database schema status for local verification."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from db.database import DEFAULT_DATABASE_PATH, connect  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Check the TwinLoop database")
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE_PATH)
    args = parser.parse_args()
    with connect(args.database) as db:
        version = db.execute(
            "SELECT value FROM schema_meta WHERE key = 'schema_version'"
        ).fetchone()
        tables = db.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
    print(f"schema_version: {version['value'] if version else 'missing'}")
    print(f"tables: {len(tables)}")
    for table in tables:
        print(f"- {table['name']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
