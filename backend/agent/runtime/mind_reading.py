"""无记忆命中后的心灵感应题反馈处理。"""
from __future__ import annotations

import json
from typing import Any
from psycopg.types.json import Jsonb
from db.database import connect


class MindReadingService:
    """保存题目和选择，并按累计证据更新性格调整记录。"""

    def create_question(self, user_id: str, avatar_id: str, dialogue_run_id: str, question: dict[str, Any]) -> dict[str, Any]:
        """创建待回答题目。"""
        with connect() as db:
            row = db.execute("INSERT INTO avatar_mind_reading_feedback(user_id,avatar_id,dialogue_run_id,question) VALUES(%s,%s,%s,%s) RETURNING id,question,status,created_at", (user_id, avatar_id, dialogue_run_id, Jsonb(question))).fetchone()
            return dict(row)

    def answer(self, question_id: str, option_id: str) -> dict[str, Any]:
        """保存用户选择并累计性格方向证据。"""
        with connect() as db:
            row = db.execute("SELECT * FROM avatar_mind_reading_feedback WHERE id=%s FOR UPDATE", (question_id,)).fetchone()
            if not row:
                raise ValueError("心灵感应题不存在")
            question = row["question"] or {}
            is_match = option_id == question.get("agent_option_id")
            db.execute("UPDATE avatar_mind_reading_feedback SET selected_option_id=%s,is_match=%s,status='answered',answered_at=now() WHERE id=%s", (option_id, is_match, question_id))
            return {"id": str(question_id), "is_match": is_match, "status": "answered"}

