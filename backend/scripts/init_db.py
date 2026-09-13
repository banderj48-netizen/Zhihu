"""Initialize the PostgreSQL database used by TwinLoop."""

from __future__ import annotations

import argparse
import sys

from pathlib import Path

import psycopg

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from db.database import initialize  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Initialize the TwinLoop PostgreSQL database")
    parser.add_argument("--url", help="PostgreSQL URL; defaults to DATABASE_URL or backend/.env")
    args = parser.parse_args()
    try:
        version = initialize(args.url)
    except (ValueError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except psycopg.Error:
        print("PostgreSQL initialization failed; verify the service, credentials and migration permissions.", file=sys.stderr)
        return 1
    print(f"PostgreSQL schema initialized successfully (version {version}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
