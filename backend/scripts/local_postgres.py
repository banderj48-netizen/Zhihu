"""Manage the optional project-local PostgreSQL 16 installation on Windows.

Binaries: backend/.postgresql/pgsql (official EDB archive).
Does not change PATH, register a Windows service, or use a system database.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
from urllib.parse import quote

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / ".postgresql"
if os.name == "nt" and not str(LOCAL).isascii():
    # PostgreSQL's Windows child processes cannot initialize in a GBK path.
    # The junction keeps the actual data in the project's ignored directory.
    LOCAL = Path(tempfile.gettempdir()) / ("twinloop-pg-" + hashlib.sha256(str(ROOT).encode()).hexdigest()[:12])
BIN = LOCAL / "pgsql" / "bin"
DATA = LOCAL / "data"
CONFIG = LOCAL / "local.json"


def run_tool(name: str, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    # A long-lived postgres process can inherit pipes from pg_ctl. Files avoid
    # waiting forever for inherited stdout/stderr to close after startup.
    command = [str(BIN / (name + ".exe")), *args]
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as error:
        process = subprocess.run(command, stdout=output, stderr=error,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        output.seek(0)
        error.seek(0)
        result = subprocess.CompletedProcess(command, process.returncode,
            output.read().decode("utf-8", errors="replace"), error.read().decode("utf-8", errors="replace"))
    if check and result.returncode:
        raise subprocess.CalledProcessError(result.returncode, command, result.stdout, result.stderr)
    return result


def config() -> dict:
    if not CONFIG.exists():
        raise RuntimeError("Run local_postgres.py init first")
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def start(settings: dict) -> None:
    if run_tool("pg_ctl", "status", "-D", str(DATA), check=False).returncode == 0:
        return
    run_tool("pg_ctl", "start", "-D", str(DATA), "-l", str(LOCAL / "server.log"), "-w", "-t", "30")


def init(port: int) -> None:
    if not (BIN / "initdb.exe").exists():
        raise RuntimeError("Extract the official PostgreSQL Windows binaries into backend/.postgresql first")
    LOCAL.mkdir(exist_ok=True)
    if not CONFIG.exists():
        if DATA.exists():
            raise RuntimeError("Existing data directory without local.json; refusing to replace it")
        settings = {
            "port": port, "admin": "twinloop_admin", "password": secrets.token_urlsafe(32),
            "app_password": secrets.token_urlsafe(32),
        }
        CONFIG.write_text(json.dumps(settings), encoding="utf-8")
    settings = config()
    if not (DATA / "PG_VERSION").exists():
        password_file = LOCAL / "init-password"
        password_file.write_text(settings["password"], encoding="utf-8")
        try:
            run_tool("initdb", "-D", str(DATA), "-U", settings["admin"],
                     "--encoding=UTF8", "--locale=C", "--auth=scram-sha-256",
                     "--pwfile=" + str(password_file))
        finally:
            password_file.unlink(missing_ok=True)
        with (DATA / "postgresql.conf").open("a", encoding="utf-8") as f:
            f.write("\nlisten_addresses = '127.0.0.1'\n")
            f.write("port = " + str(settings["port"]) + "\n")
            f.write("timezone = 'UTC'\n")
    start(settings)
    admin = make_conninfo(host="127.0.0.1", port=settings["port"], dbname="postgres",
                         user=settings["admin"], password=settings["password"], connect_timeout=5)
    with psycopg.connect(admin, autocommit=True) as db:
        if not db.execute("SELECT 1 FROM pg_roles WHERE rolname = 'twinloop'").fetchone():
            db.execute(sql.SQL("CREATE ROLE twinloop LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD {}")
                       .format(sql.Literal(settings["app_password"])))
        if not db.execute("SELECT 1 FROM pg_database WHERE datname = 'twinloop'").fetchone():
            db.execute("CREATE DATABASE twinloop OWNER twinloop ENCODING 'UTF8'")
    env = ROOT / ".env"
    if not env.exists():
        env.write_text("DATABASE_URL=postgresql://twinloop:" + quote(settings["app_password"], safe="")
                       + "@127.0.0.1:" + str(settings["port"]) + "/twinloop\n", encoding="utf-8")
    print(f"Local PostgreSQL ready at 127.0.0.1:{settings['port']}/twinloop. Credentials in ignored local files.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["init", "start", "stop", "status"])
    parser.add_argument("--port", type=int, default=5432)
    args = parser.parse_args()
    target = ROOT / ".postgresql"
    if LOCAL.exists() and LOCAL.resolve() != target.resolve():
        raise RuntimeError("Local PostgreSQL path points outside this project; refusing to use it")
    if LOCAL != target and not LOCAL.exists() and target.exists():
        escaped_alias = str(LOCAL).replace("'", "''")
        escaped_target = str(target).replace("'", "''")
        subprocess.run(["powershell.exe", "-NoProfile", "-Command",
            f"New-Item -ItemType Junction -Path '{escaped_alias}' -Target '{escaped_target}' | Out-Null"],
            check=True, creationflags=subprocess.CREATE_NO_WINDOW)
    if args.action == "init":
        init(args.port)
    elif args.action == "start":
        start(config())
        print("Local PostgreSQL started.")
    elif args.action == "stop":
        config()
        run_tool("pg_ctl", "stop", "-D", str(DATA), "-m", "fast", "-w", "-t", "30")
        print("Local PostgreSQL stopped.")
    else:
        result = run_tool("pg_ctl", "status", "-D", str(DATA), check=False)
        print("Local PostgreSQL is running." if result.returncode == 0 else "Local PostgreSQL is stopped.")
        return result.returncode
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        # PostgreSQL startup output contains no connection credentials.
        print(exc.stderr or exc.stdout or "PostgreSQL operation failed", file=sys.stderr)
        raise SystemExit(1)
