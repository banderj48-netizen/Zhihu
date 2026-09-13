"""数字分身初始化流程编排。"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4
from psycopg.types.json import Jsonb

from db.database import connect
from agent.personality.assessment import score_assessment
from agent.profile.repository import ProfileRepository


def _now() -> datetime:
    """返回带时区的当前时间。"""
    return datetime.now(timezone.utc)


class InitializationService:
    """复用既有导入、测评和画像仓储的初始化服务。"""

    def create(self, user_id: str, import_job_id: str | None = None) -> dict[str, Any]:
        """创建用户唯一的初始化会话。"""
        with connect() as db:
            row = db.execute("""INSERT INTO avatar_initialization_sessions(user_id,import_job_id,status,current_step)
                VALUES(%s,%s,'importing','importing')
                ON CONFLICT(user_id) DO UPDATE SET updated_at=now()
                RETURNING id,user_id,import_job_id,status,current_step,input_data,generated_profile,created_at,updated_at""",
                (user_id, import_job_id)).fetchone()
            return dict(row)

    def get(self, session_id: str) -> dict[str, Any] | None:
        """读取初始化会话。"""
        with connect() as db:
            row = db.execute("SELECT * FROM avatar_initialization_sessions WHERE id=%s", (session_id,)).fetchone()
            return dict(row) if row else None

    def save_step(self, session_id: str, step: str, payload: dict[str, Any]) -> dict[str, Any]:
        """保存一个初始化步骤并推进状态。"""
        mapping = {"personality": "personality_pending", "domains": "domain_pending", "opinion-answers": "social_questions_pending", "social-answers": "generating_profile"}
        status = mapping.get(step, "review")
        with connect() as db:
            row = db.execute("""UPDATE avatar_initialization_sessions
                SET current_step=%s,status=%s,input_data=input_data || %s,updated_at=now()
                WHERE id=%s RETURNING *""", (step, status, Jsonb({step: payload}), session_id)).fetchone()
            if not row:
                raise ValueError("初始化会话不存在")
            return dict(row)

    async def complete(self, session_id: str, identity: dict[str, Any]) -> dict[str, Any]:
        """根据已保存结果创建初始画像版本并完成初始化。"""
        session = self.get(session_id)
        if not session:
            raise ValueError("初始化会话不存在")
        data = session.get("input_data") or {}
        personality = data.get("personality", {})
        # 画像生成第一版采用已有测评与用户选择，后续可替换为结构化 LLM 提炼器。
        result = await asyncio.to_thread(ProfileRepository().initialize_avatar, user_id=str(session["user_id"]), identity=identity, personality=personality, style=data.get("style", {}), policy=data.get("policy", {}))
        with connect() as db:
            db.execute("UPDATE avatar_initialization_sessions SET status='completed',current_step='completed',generated_profile=%s,completed_at=now(),updated_at=now() WHERE id=%s", (Jsonb(result), session_id))
        return result
