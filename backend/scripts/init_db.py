"""Create or verify the local TwinLoop database."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from db.database import DEFAULT_DATABASE_PATH, initialize  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Initialize the TwinLoop SQLite database")
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE_PATH)
    args = parser.parse_args()
    path = initialize(args.database)
    print(f"database initialized: {path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
