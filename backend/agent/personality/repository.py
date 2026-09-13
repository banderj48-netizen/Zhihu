"""Persistence bridge for personality results.

This module is intentionally small: the Agent calculates a result, while the
repository stores an immutable assessment row and the traditional profile
service decides when it becomes the current profile version.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from db.database import DEFAULT_DATABASE_PATH, connect, initialize


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _database_path() -> Path:
    return Path(os.getenv("TWINLOOP_DATABASE_PATH", str(DEFAULT_DATABASE_PATH)))


def _ensure_avatar(db: sqlite3.Connection, user_id: str) -> str:
    now = _now()
    db.execute(
        "INSERT INTO users(id, created_at, updated_at) VALUES (?, ?, ?) ON CONFLICT(id) DO UPDATE SET updated_at=excluded.updated_at",
        (user_id, now, now),
    )
    row = db.execute(
        "SELECT id FROM avatars WHERE user_id = ? AND deleted_at IS NULL ORDER BY created_at, id LIMIT 1", (user_id,)
    ).fetchone()
    if row:
        return row["id"]
    avatar_id = f"avatar_{uuid4().hex}"
    db.execute(
        "INSERT INTO avatars(id, user_id, status, created_at, updated_at) VALUES (?, ?, 'not_started', ?, ?)",
        (avatar_id, user_id, now, now),
    )
    return avatar_id


def save_assessment(user_id: str, result: dict, request_key: str | None = None) -> dict:
    """Persist a result and return it. Repeated request keys are idempotent."""

    path = _database_path()
    initialize(path)
    with connect(path) as db:
        avatar_id = _ensure_avatar(db, user_id)
        if request_key:
            existing = db.execute(
                "SELECT result_json FROM personality_assessments WHERE avatar_id = ? AND request_key = ?",
                (avatar_id, request_key),
            ).fetchone()
            if existing:
                return json.loads(existing["result_json"])
        assessment_id = result["assessment_id"]
        now = _now()
        db.execute(
            """INSERT INTO personality_assessments
            (id, avatar_id, instrument_version, status, raw_answers_json,
             scores_json, confidence, validity_json, source_mix_json, skipped,
             created_at, completed_at, result_json, request_key)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)""",
            (
                assessment_id,
                avatar_id,
                result["instrument_version"],
                result["status"],
                json.dumps(result["raw_answers"], ensure_ascii=False),
                json.dumps({"scores": result["scores"], "raw_means": result["raw_means"]}, ensure_ascii=False),
                result["confidence"],
                json.dumps(result["validity"], ensure_ascii=False),
                json.dumps({"source": result["source"], "data_quality": result["data_quality"], "style_tags": result["style_tags"]}, ensure_ascii=False),
                now,
                now,
                json.dumps(result, ensure_ascii=False),
                request_key,
            ),
        )
    return result


def save_skipped(user_id: str, assessment_id: str, request_key: str | None = None) -> dict:
    path = _database_path()
    initialize(path)
    result = {
        "model": "big_five",
        "instrument_version": "ipip-big-five-50-zh-v1",
        "assessment_id": assessment_id,
        "status": "skipped",
        "source": "none",
        "scores": {key: None for key in ("extraversion", "agreeableness", "conscientiousness", "neuroticism", "openness")},
        "style_tags": [],
        "confidence": 0.0,
        "data_quality": 0.0,
        "validity": {"answered_count": 0, "total_count": 50, "flags": ["skipped"], "usable": False},
        "raw_answers": {},
        "raw_means": {key: None for key in ("extraversion", "agreeableness", "conscientiousness", "neuroticism", "openness")},
        "privacy": "private",
        "share": False,
    }
    with connect(path) as db:
        avatar_id = _ensure_avatar(db, user_id)
        if request_key:
            existing = db.execute(
                "SELECT result_json FROM personality_assessments WHERE avatar_id = ? AND request_key = ?",
                (avatar_id, request_key),
            ).fetchone()
            if existing:
                return json.loads(existing["result_json"])
        now = _now()
        db.execute(
            """INSERT INTO personality_assessments
            (id, avatar_id, instrument_version, status, raw_answers_json,
             scores_json, confidence, validity_json, source_mix_json, skipped,
             created_at, completed_at, result_json, request_key)
            VALUES (?, ?, ?, 'skipped', '{}', '{}', 0, ?, ?, 1, ?, ?, ?, ?)""",
            (assessment_id, avatar_id, result["instrument_version"], json.dumps(result["validity"]), json.dumps({"source": "none"}), now, now, json.dumps(result, ensure_ascii=False), request_key),
        )
    return result


def latest_assessment(user_id: str) -> dict | None:
    path = _database_path()
    initialize(path)
    with connect(path) as db:
        row = db.execute(
            """SELECT p.result_json FROM personality_assessments p
            JOIN avatars a ON a.id = p.avatar_id
            JOIN users u ON u.id = a.user_id
            WHERE u.id = ? AND a.deleted_at IS NULL
            ORDER BY p.created_at DESC LIMIT 1""",
            (user_id,),
        ).fetchone()
    return json.loads(row["result_json"]) if row and row["result_json"] else None
