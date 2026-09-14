"""PostgreSQL persistence bridge for personality assessment results."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb

from db.database import connect


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _upsert_user(db, user_id: str, now: str) -> None:
    """把登录系统字符串 ID 写入正式 users 表：UUID 作主键，其余登记为 external_id。"""
    try:
        value = str(UUID(str(user_id)))
    except (ValueError, TypeError, AttributeError):
        db.execute(
            "INSERT INTO users(external_id, created_at, updated_at) VALUES (%s, %s, %s) "
            "ON CONFLICT(external_id) DO UPDATE SET updated_at=EXCLUDED.updated_at",
            (str(user_id), now, now),
        )
        return
    db.execute(
        "INSERT INTO users(id, created_at, updated_at) VALUES (%s, %s, %s) "
        "ON CONFLICT(id) DO UPDATE SET updated_at=EXCLUDED.updated_at",
        (value, now, now),
    )


def _ensure_avatar(db, user_id: str) -> str:
    now = _now()
    _upsert_user(db, user_id, now)
    row = db.execute(
        "SELECT id FROM avatars WHERE user_id = %s AND deleted_at IS NULL ORDER BY created_at, id LIMIT 1", (user_id,)
    ).fetchone()
    if row:
        return row["id"]
    avatar_id = f"avatar_{uuid4().hex}"
    db.execute(
        "INSERT INTO avatars(id, user_id, status, created_at, updated_at) VALUES (%s, %s, 'not_started', %s, %s)",
        (avatar_id, user_id, now, now),
    )
    return avatar_id


def save_assessment(user_id: str, result: dict, request_key: str | None = None) -> dict:
    with connect() as db:
        avatar_id = _ensure_avatar(db, user_id)
        if request_key:
            existing = db.execute(
                "SELECT result_json FROM personality_assessments WHERE avatar_id = %s AND request_key = %s", (avatar_id, request_key)
            ).fetchone()
            if existing:
                return existing["result_json"]
        now = _now()
        db.execute(
            """INSERT INTO personality_assessments
            (id, avatar_id, instrument_version, status, raw_answers_json,
             scores_json, confidence, validity_json, source_mix_json, skipped,
             created_at, completed_at, result_json, request_key)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, FALSE, %s, %s, %s, %s)""",
            (result["assessment_id"], avatar_id, result["instrument_version"], result["status"],
             Jsonb(result["raw_answers"]),
             Jsonb({"scores": result["scores"], "raw_means": result["raw_means"]}),
             result["confidence"], Jsonb(result["validity"]),
             Jsonb({"source": result["source"], "data_quality": result["data_quality"], "style_tags": result["style_tags"]}),
             now, now, Jsonb(result), request_key),
        )
    return result


def save_skipped(user_id: str, assessment_id: str, request_key: str | None = None) -> dict:
    dimensions = ("extraversion", "agreeableness", "conscientiousness", "neuroticism", "openness")
    result = {
        "model": "big_five", "instrument_version": "ipip-big-five-50-zh-v1", "assessment_id": assessment_id,
        "status": "skipped", "source": "none", "scores": {key: None for key in dimensions}, "style_tags": [],
        "confidence": 0.0, "data_quality": 0.0,
        "validity": {"answered_count": 0, "total_count": 50, "flags": ["skipped"], "usable": False},
        "raw_answers": {}, "raw_means": {key: None for key in dimensions}, "privacy": "private", "share": False,
    }
    with connect() as db:
        avatar_id = _ensure_avatar(db, user_id)
        if request_key:
            existing = db.execute(
                "SELECT result_json FROM personality_assessments WHERE avatar_id = %s AND request_key = %s", (avatar_id, request_key)
            ).fetchone()
            if existing:
                return existing["result_json"]
        now = _now()
        db.execute(
            """INSERT INTO personality_assessments
            (id, avatar_id, instrument_version, status, raw_answers_json,
             scores_json, confidence, validity_json, source_mix_json, skipped,
             created_at, completed_at, result_json, request_key)
            VALUES (%s, %s, %s, 'skipped', '{}', '{}', 0, %s, %s, TRUE, %s, %s, %s, %s)""",
            (assessment_id, avatar_id, result["instrument_version"], Jsonb(result["validity"]), Jsonb({"source": "none"}), now, now, Jsonb(result), request_key),
        )
    return result


def latest_assessment(user_id: str) -> dict | None:
    with connect() as db:
        row = db.execute(
            "SELECT p.result_json FROM personality_assessments p JOIN avatars a ON a.id = p.avatar_id "
            "JOIN users u ON (u.id::text = a.user_id OR u.external_id = a.user_id) "
            "WHERE a.user_id = %s AND a.deleted_at IS NULL AND u.deleted_at IS NULL "
            "ORDER BY p.created_at DESC, p.id DESC LIMIT 1",
            (user_id,),
        ).fetchone()
    return row["result_json"] if row and row["result_json"] else None
