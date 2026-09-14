"""数字分身初始化流程编排。"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4, UUID
from psycopg.types.json import Jsonb

from db.database import connect
from agent.personality.assessment import score_assessment
from agent.profile.repository import ProfileRepository


def _now() -> datetime:
    """返回带时区的当前时间。"""
    return datetime.now(timezone.utc)


class InitializationService:
    """复用既有导入、测评和画像仓储的初始化服务。"""

    def create(self, user_id: str, import_job_id: str | None = None, zhihu_token: str | None = None) -> dict[str, Any]:
        """创建会话，并在同一流程抓取知乎资料、生成领域预选。"""
        imported: dict[str, Any] = {}
        if zhihu_token:
            from app.imports import zhihu_client
            for key, fn in (("contents", zhihu_client.fetch_contents), ("followees", zhihu_client.fetch_followees), ("favlists", zhihu_client.fetch_favlists), ("collections", zhihu_client.fetch_collections)):
                try: imported[key] = fn(zhihu_token)
                except Exception as exc: imported[key] = {"error": str(exc)}
        domains = []
        try:
            from agent.domains.catalog import search
            domains = search(None, None, None)
        except Exception: pass
        recommended = []
        try:
            from agent.runtime.model_builder import build_llm
            prompt = "根据以下知乎资料和领域目录，返回JSON数组，推荐用户感兴趣或擅长的领域，每项包含domain_id、kind(interests/expertise)、level和reason。只输出JSON。知乎资料：" + json.dumps(imported, ensure_ascii=False)[:12000] + " 领域目录：" + json.dumps(domains, ensure_ascii=False)[:12000]
            raw = asyncio.run(build_llm().generate(prompt, temperature=0.2, max_tokens=1200))
            recommended = json.loads(raw.text[raw.text.find("["):raw.text.rfind("]") + 1])
        except Exception: recommended = []
        with connect() as db:
            user_id = self._ensure_uuid_user(db, user_id)
            row = db.execute("""INSERT INTO avatar_initialization_sessions(user_id,import_job_id,status,current_step)
                VALUES(%s,%s,'importing','importing')
                ON CONFLICT(user_id) DO UPDATE SET updated_at=now()
                RETURNING id,user_id,import_job_id,status,current_step,input_data,generated_profile,created_at,updated_at""",
                (user_id, import_job_id)).fetchone()
            if imported or recommended:
                row = db.execute("UPDATE avatar_initialization_sessions SET input_data=input_data || %s, status='domain_pending', current_step='domains_review', updated_at=now() WHERE id=%s RETURNING id,user_id,import_job_id,status,current_step,input_data,generated_profile,created_at,updated_at", (Jsonb({'zhihu': imported, 'domain_recommendations': recommended}), row['id'])).fetchone()
            return dict(row)

    @staticmethod
    def _ensure_uuid_user(db, user_id: str) -> str:
        """将登录系统的字符串 ID 映射到画像库 UUID。"""
        try:
            value = str(UUID(str(user_id)))
            db.execute("INSERT INTO users(id) VALUES(%s) ON CONFLICT(id) DO NOTHING", (value,))
            return value
        except (ValueError, TypeError, AttributeError):
            existing = db.execute("SELECT id FROM users WHERE external_id=%s AND deleted_at IS NULL", (str(user_id),)).fetchone()
            if existing:
                return str(existing["id"])
            value = str(uuid4())
            db.execute("INSERT INTO users(id,external_id) VALUES(%s,%s)", (value, str(user_id)))
            return value

    def get(self, session_id: str, user_id: str | None = None) -> dict[str, Any] | None:
        """读取初始化会话。"""
        with connect() as db:
            row = db.execute("SELECT * FROM avatar_initialization_sessions WHERE id=%s", (session_id,)).fetchone()
            if row and user_id is not None:
                owner = self._find_user(db, user_id)
                if not owner or str(owner["id"]) != str(row["user_id"]):
                    return None
            return dict(row) if row else None

    def save_step(self, session_id: str, step: str, payload: dict[str, Any], user_id: str | None = None) -> dict[str, Any]:
        """保存一个初始化步骤并推进状态。"""
        mapping = {"personality": "personality_pending", "domains": "domain_pending", "opinion-answers": "opinion_questions_pending", "social-answers": "generating_profile"}
        status = mapping.get(step, "review")
        with connect() as db:
            owner_clause = ""
            params: list[Any] = [step, status, Jsonb({step: payload}), session_id]
            if user_id is not None:
                owner = self._find_user(db, user_id)
                if not owner:
                    raise ValueError("初始化会话不存在")
                owner_clause = " AND user_id=%s"
                params.append(owner["id"])
            row = db.execute("""UPDATE avatar_initialization_sessions
                SET current_step=%s,status=%s,input_data=input_data || %s,updated_at=now()
                WHERE id=%s""".replace("WHERE id=%s", "WHERE id=%s" + owner_clause) + " RETURNING *", params).fetchone()
            if not row:
                raise ValueError("初始化会话不存在")
            return dict(row)

    @staticmethod
    def _find_user(db, user_id: str):
        """查找内部 UUID 或登录系统 external_id，避免向 uuid 列传入任意字符串。"""
        try:
            value = str(UUID(str(user_id)))
        except (ValueError, TypeError, AttributeError):
            return db.execute("SELECT id FROM users WHERE external_id=%s AND deleted_at IS NULL", (str(user_id),)).fetchone()
        return db.execute("SELECT id FROM users WHERE id=%s AND deleted_at IS NULL", (value,)).fetchone()

    async def complete(self, session_id: str, identity: dict[str, Any], user_id: str | None = None) -> dict[str, Any]:
        """根据已保存结果创建初始画像版本并完成初始化。"""
        session = self.get(session_id, user_id=user_id)
        if not session:
            raise ValueError("初始化会话不存在")
        data = session.get("input_data") or {}
        personality = data.get("personality", {})
        # API may receive raw answers or an already scored assessment result.
        if isinstance(personality, dict) and "answers" in personality and "scores" not in personality:
            personality = score_assessment(personality["answers"], personality.get("assessment_id", f"assessment_{uuid4().hex}"), personality.get("notes"))
        elif isinstance(personality, dict) and "scores" in personality:
            personality = {**personality, "model_name": personality.get("model_name", personality.get("model", "big_five")), "inference_source": personality.get("inference_source", personality.get("source", "self_report")), "status": personality.get("status") if personality.get("status") in {"confirmed", "unconfirmed", "rejected"} else "unconfirmed"}
        if isinstance(personality, dict):
            personality["status"] = personality.get("status") if personality.get("status") in {"confirmed", "unconfirmed", "rejected"} else "unconfirmed"
        # 画像生成第一版采用已有测评与用户选择，后续可替换为结构化 LLM 提炼器。
        repo = ProfileRepository()
        result = await asyncio.to_thread(repo.initialize_avatar, user_id=str(session["user_id"]), identity=identity, personality=personality, style=data.get("style", {}), policy=data.get("policy", {}))
        # Preserve all initialization inputs as auditable source documents and
        # derive dynamic memories from domain/opinion/social answers.
        avatar_id, version_id = result["avatar_id"], result["version_id"]
        source_ids: dict[str, str] = {}
        for key, dtype in (("personality", "personality_answer"), ("domains", "domain_selection"), ("opinion-answers", "opinion_answer"), ("social-answers", "social_answer")):
            if key in data:
                source_ids[key] = await asyncio.to_thread(repo.write_source, user_id=str(session["user_id"]), avatar_id=avatar_id, platform="twinloop", document_type=dtype, content=json.dumps(data[key], ensure_ascii=False), external_id=f"{session_id}:{key}")

        def apply(payload: dict[str, Any], proposal_type: str, source_key: str):
            nonlocal version_id
            from agent.profile.proposals import ProfileProposal
            value = repo.apply_memory_proposal(ProfileProposal(user_id=str(session["user_id"]), avatar_id=avatar_id, base_version_id=version_id, proposal_type=proposal_type, payload=payload, source_refs=[source_ids[source_key]] if source_key in source_ids else []))
            version_id = value["version_id"]
            return value

        for item in (data.get("domains", {}).get("interests", []) if isinstance(data.get("domains"), dict) else []):
            apply({"memory_type": "interest", "level": "shallow", "topic": item.get("domain_id"), "content": item.get("notes") or f"对领域 {item.get('domain_id')} 感兴趣", "structured_data": item}, "propose_interest_memory", "domains")
        for item in (data.get("domains", {}).get("expertise", []) if isinstance(data.get("domains"), dict) else []):
            apply({"memory_type": "expertise", "level": "middle", "topic": item.get("domain_id"), "content": item.get("notes") or f"自评擅长领域 {item.get('domain_id')}", "structured_data": item}, "propose_expertise_memory", "domains")
        for item in (data.get("opinion-answers", {}).get("answers", []) if isinstance(data.get("opinion-answers"), dict) else []):
            apply({"memory_type": "opinion", "level": item.get("level", "middle"), "topic": item.get("topic"), "content": item.get("custom_text") or item.get("content") or f"选择选项 {item.get('selected_option_id')}", "structured_data": item}, "propose_opinion_memory", "opinion-answers")
        for item in (data.get("social-answers", {}).get("answers", []) if isinstance(data.get("social-answers"), dict) else []):
            elapsed = item.get("elapsed_seconds")
            if elapsed is not None and float(elapsed) > 13:
                continue
            apply({"memory_type": "behavior", "level": item.get("level", "middle"), "topic": item.get("topic"), "content": item.get("custom_text") or item.get("reaction") or f"在情景题中选择 {item.get('selected_option_id')}", "structured_data": item}, "propose_behavior_memory", "social-answers")
        # Return the actually active version after dynamic memories were merged.
        result["version_id"] = version_id
        with connect() as db:
            db.execute("UPDATE avatar_initialization_sessions SET status='completed',current_step='completed',generated_profile=%s,completed_at=now(),updated_at=now() WHERE id=%s", (Jsonb(result), session_id))
        return result
