"""无记忆命中后的心灵感应题反馈处理。"""
from __future__ import annotations

import json
import os
from typing import Any
from decimal import Decimal
from psycopg.types.json import Jsonb
from db.database import connect


class MindReadingService:
    """保存题目和选择，并按累计证据更新性格调整记录。"""

    def create_question(self, user_id: str, avatar_id: str, dialogue_run_id: str, question: dict[str, Any]) -> dict[str, Any]:
        """创建待回答题目。"""
        with connect() as db:
            row = db.execute("""INSERT INTO avatar_mind_reading_feedback
                (user_id,avatar_id,dialogue_run_id,question,agent_option_id,personality_dimension)
                VALUES(%s,%s,%s,%s,%s,%s)
                RETURNING id,question,status,created_at""", (user_id, avatar_id, dialogue_run_id,
                Jsonb(question), question.get("agent_option_id"), question.get("personality_dimension"))).fetchone()
            return dict(row)

    def answer(self, question_id: str, option_id: str) -> dict[str, Any]:
        """保存用户选择并累计性格方向证据。

        The server validates the option and makes answers idempotent.  A valid
        answer is marked ``applied`` after its optional personality signal has
        been folded into a new avatar version; malformed or repeated answers
        never mutate the profile.
        """
        with connect() as db:
            row = db.execute("SELECT * FROM avatar_mind_reading_feedback WHERE id=%s FOR UPDATE", (question_id,)).fetchone()
            if not row:
                raise ValueError("心灵感应题不存在")
            question = row["question"] or {}
            if row["status"] != "pending":
                # A second submission should be harmless and return the
                # original result rather than overwrite an audited answer.
                return {"id": str(question_id), "is_match": row["is_match"], "status": row["status"], "selected_option_id": row["selected_option_id"]}
            options = question.get("options") or []
            option_ids = {str(item.get("id")) for item in options if isinstance(item, dict) and item.get("id") is not None}
            if option_ids and option_id not in option_ids:
                raise ValueError("option_id 不在题目选项中")
            is_match = option_id == question.get("agent_option_id")
            db.execute("UPDATE avatar_mind_reading_feedback SET selected_option_id=%s,is_match=%s,status='answered',answered_at=now() WHERE id=%s", (option_id, is_match, question_id))

            # Record cumulative growth metrics for every valid answer.  This
            # remains useful even when a question carries no personality
            # dimension (for example, a pure preference probe).
            totals = db.execute("""SELECT count(*) AS total,
                    count(*) FILTER (WHERE is_match) AS matches
                FROM avatar_mind_reading_feedback
                WHERE avatar_id=%s AND status IN ('answered','applied')""", (row["avatar_id"],)).fetchone()
            round_no = db.execute("SELECT COALESCE(MAX(round_no),0)+1 AS n FROM avatar_growth_evaluations WHERE avatar_id=%s", (row["avatar_id"],)).fetchone()["n"]
            total = int(totals["total"] or 0)
            matches = int(totals["matches"] or 0)
            accuracy = (Decimal(matches) / Decimal(total)) if total else None
            db.execute("""INSERT INTO avatar_growth_evaluations
                (avatar_id, round_no, match_count, accuracy, metric_detail, evaluated_at)
                VALUES (%s,%s,%s,%s,%s,now())""", (row["avatar_id"], round_no, matches, accuracy,
                Jsonb({"source": "mind_reading", "feedback_id": str(question_id), "total": total})))

            dimension = row.get("personality_dimension") or question.get("personality_dimension")
            adjustment = None
            if dimension:
                adjustment = self._apply_personality_adjustment(db, row, question, dimension, bool(is_match), question_id)
                if adjustment and adjustment.get("version_id"):
                    db.execute("UPDATE avatar_growth_evaluations SET version_id=%s WHERE avatar_id=%s AND round_no=%s", (adjustment["version_id"], row["avatar_id"], round_no))
            # Mark applied only after all derived records have succeeded.
            db.execute("UPDATE avatar_mind_reading_feedback SET status='applied' WHERE id=%s", (question_id,))
            return {"id": str(question_id), "is_match": is_match, "status": "applied", "selected_option_id": option_id, "personality_adjustment": adjustment}

    def _apply_personality_adjustment(self, db, feedback, question: dict[str, Any], dimension: str, is_match: bool, question_id: str) -> dict[str, Any]:
        """Create a versioned personality adjustment when the question opts in."""
        # Questions may specify a signed delta; otherwise matching reinforces
        # the agent's prediction and a mismatch nudges it in the opposite
        # direction.  Keep changes deliberately small and bounded.
        raw_delta = question.get("adjustment", 0.1)
        try:
            magnitude = min(max(abs(float(raw_delta)), 0.01), 1.0)
        except (TypeError, ValueError):
            magnitude = 0.1
        delta = magnitude if is_match else -magnitude
        direction = "increase" if delta > 0 else "decrease"
        threshold = max(1, int(os.getenv("MIND_READING_ADJUSTMENT_THRESHOLD", "3")))
        evidence = db.execute("""SELECT COALESCE(SUM(evidence_count),0) AS n
            FROM avatar_personality_adjustments
            WHERE avatar_id=%s AND dimension=%s AND direction=%s""",
            (feedback["avatar_id"], dimension, direction)).fetchone()
        accumulated = int(evidence["n"] or 0) + 1
        avatar = db.execute("SELECT id,current_version_id FROM user_avatars WHERE id=%s FOR UPDATE", (feedback["avatar_id"],)).fetchone()
        if not avatar or not avatar["current_version_id"]:
            return {"dimension": dimension, "delta": delta, "applied": False, "reason": "avatar_not_initialized"}
        old_id = avatar["current_version_id"]
        old_version = db.execute("SELECT version_no FROM avatar_versions WHERE id=%s", (old_id,)).fetchone()
        personality = db.execute("SELECT * FROM avatar_personality WHERE avatar_version_id=%s", (old_id,)).fetchone()
        if not personality:
            return {"dimension": dimension, "delta": delta, "applied": False, "reason": "personality_not_initialized"}
        scores = dict(personality["scores"] or {})
        before = scores.get(dimension)
        if before is None:
            return {"dimension": dimension, "delta": delta, "applied": False, "reason": "unknown_dimension"}
        # Keep a single noisy answer from moving the stable personality model.
        # Every answer is recorded; only the configured cumulative threshold
        # produces a new personality version.
        if accumulated < threshold:
            db.execute("""INSERT INTO avatar_personality_adjustments
                (avatar_id,dimension,direction,evidence_count,before_value,after_value,reason)
                VALUES(%s,%s,%s,1,%s,%s,%s)""", (feedback["avatar_id"], dimension, direction, before, before, f"mind_reading:{question_id}:accumulating"))
            return {"dimension": dimension, "delta": 0, "applied": False, "evidence_count": accumulated, "threshold": threshold}
        after = round(min(10.0, max(0.0, float(before) + delta)), 2)
        scores[dimension] = after
        # Keep the immutable version snapshot aligned with the normalized
        # personality row so exports and rollback see the same result.
        base_snapshot = db.execute("SELECT snapshot FROM avatar_versions WHERE id=%s", (old_id,)).fetchone()["snapshot"] or {}
        snapshot = dict(base_snapshot)
        snapshot_personality = dict(snapshot.get("personality") or {})
        snapshot_personality["scores"] = scores
        snapshot_personality["inference_source"] = "mind_reading_feedback"
        snapshot["personality"] = snapshot_personality
        new_version = db.execute("""INSERT INTO avatar_versions
            (avatar_id,version_no,source_type,base_version_id,status,change_summary,snapshot,created_by)
            VALUES(%s,%s,'system_merge',%s,'draft',%s,%s,'system') RETURNING id,version_no""", (avatar["id"], int(old_version["version_no"]) + 1, old_id, "mind_reading_personality_adjustment", Jsonb(snapshot))).fetchone()
        db.execute("UPDATE avatar_versions SET status='superseded' WHERE id=%s", (old_id,))
        db.execute("UPDATE avatar_versions SET status='active',activated_at=now() WHERE id=%s", (new_version["id"],))
        db.execute("UPDATE user_avatars SET current_version_id=%s,updated_at=now() WHERE id=%s", (new_version["id"], avatar["id"]))
        # Copy fixed identity and style rows for the new snapshot version.
        db.execute("""INSERT INTO avatar_identity(avatar_version_id,display_name,summary,occupation,location,age,privacy_level,extra)
            SELECT %s,display_name,summary,occupation,location,age,privacy_level,extra FROM avatar_identity WHERE avatar_version_id=%s""", (new_version["id"], old_id))
        db.execute("""INSERT INTO avatar_styles(avatar_version_id,tone,structure_rules,verbosity,technical_density,sentence_style,uncertainty_style,preferred_registers,avoid_rules,extra)
            SELECT %s,tone,structure_rules,verbosity,technical_density,sentence_style,uncertainty_style,preferred_registers,avoid_rules,extra FROM avatar_styles WHERE avatar_version_id=%s""", (new_version["id"], old_id))
        db.execute("""INSERT INTO avatar_personality(avatar_version_id,model_name,scores,style_tags,confidence,inference_source,status)
            VALUES(%s,%s,%s,%s,%s,%s,%s)""", (new_version["id"], personality["model_name"], Jsonb(scores), personality["style_tags"], personality["confidence"], "mind_reading_feedback", personality["status"]))
        db.execute("""INSERT INTO avatar_personality_adjustments(avatar_id,dimension,direction,evidence_count,before_value,after_value,reason)
            VALUES(%s,%s,%s,%s,%s,%s,%s)""", (avatar["id"], dimension, direction, accumulated, before, after, f"mind_reading:{question_id}"))
        db.execute("""INSERT INTO avatar_change_logs(avatar_id,version_id,operator_type,operation,target_type,target_id,after_data,reason)
            VALUES(%s,%s,'system','update','avatar_personality',NULL,%s,%s)""", (avatar["id"], new_version["id"], Jsonb({"dimension": dimension, "before": before, "after": after}), f"mind_reading:{question_id}"))
        return {"dimension": dimension, "before": before, "after": after, "delta": delta, "version_id": str(new_version["id"]), "applied": True}

