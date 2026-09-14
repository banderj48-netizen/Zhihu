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


def _parse_profile_json(text: str) -> dict[str, Any] | None:
    """从模型文本中提取画像 JSON，兼容 Markdown 包裹并拒绝不完整结构。"""
    cleaned = text.strip().replace("```json", "").replace("```", "").strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        value = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


async def _generate_profile_draft(data: dict[str, Any]) -> dict[str, Any] | None:
    """调用真实 LLM 生成紧凑画像草稿，解析失败时用严格短格式重试。"""
    from agent.runtime.model_builder import build_llm

    base = json.dumps(data, ensure_ascii=False)[:20000]
    prompts = [
        "请根据以下知乎资料、领域选择、性格、观点和社交答案生成数字分身画像。只输出严格 JSON，不要 Markdown。字段必须包含 summary(string)、style(object)、interests(array，最多5项)、expertise(array，最多5项)、opinions(object，最多4项)、behaviors(object，最多4项)。每个数组项使用不超过40字的字符串或简短对象，全部内容使用中文，避免重复和长篇解释。资料：" + base,
        "请把以下资料压缩成一份简短数字分身画像，只输出一行严格 JSON：summary、style、interests（最多3项）、expertise（最多3项）、opinions（最多3项）、behaviors（最多3项）。不要 Markdown、不要解释、不要额外字段。资料：" + base,
    ]
    for index, prompt in enumerate(prompts):
        try:
            raw = await build_llm().generate(prompt, temperature=0.2, max_tokens=4200 if index == 0 else 2600)
            value = _parse_profile_json(raw.text)
            if value:
                return value
            print(f"[initialization] profile JSON parse failed on attempt {index + 1}", flush=True)
        except Exception as exc:
            print(f"[initialization] profile draft attempt {index + 1} failed: {type(exc).__name__}: {exc!r}", flush=True)
    return None


class InitializationService:
    """复用既有导入、测评和画像仓储的初始化服务。"""

    def create(self, user_id: str, import_job_id: str | None = None, zhihu_token: str | None = None) -> dict[str, Any]:
        """创建会话，并在同一流程抓取知乎资料、生成领域预选。"""
        print(f"[initialization] create user={user_id}", flush=True)
        imported: dict[str, Any] = {}
        if zhihu_token:
            from app.imports import zhihu_client
            for key, fn in (("contents", zhihu_client.fetch_contents), ("followees", zhihu_client.fetch_followees), ("favlists", zhihu_client.fetch_favlists), ("collections", zhihu_client.fetch_collections)):
                try:
                    imported[key] = fn(zhihu_token)
                    print(f"[initialization] zhihu {key} fetched", flush=True)
                except Exception as exc:
                    imported[key] = {"error": str(exc)}
                    print(f"[initialization] zhihu {key} failed: {exc}", flush=True)
        domains = []
        try:
            from agent.domains.catalog import search
            domains = search(None, None, None)
            print(f"[initialization] domain catalog loaded count={len(domains)}", flush=True)
        except Exception as exc:
            print(f"[initialization] domain catalog load failed: {type(exc).__name__}: {exc!r}", flush=True)
        recommended = []
        try:
            from agent.runtime.model_builder import build_llm
            imported_json = json.dumps(imported, ensure_ascii=False)
            domains_json = json.dumps(domains, ensure_ascii=False)
            print(f"[initialization] LLM input prepared zhihu_chars={len(imported_json)} domain_count={len(domains)}", flush=True)
            prompt = "根据以下知乎资料和领域目录，推荐用户感兴趣或擅长的领域。只输出一个JSON数组，不要输出思考过程、Markdown或其他文字；每项包含domain_id、kind(interests/expertise)、level和reason，最多推荐10项。知乎资料：" + imported_json[:12000] + " 领域目录：" + domains_json[:12000]
            print(f"[initialization] LLM prompt assembled chars={len(prompt)}", flush=True)
            print(f"[initialization] LLM prompt full: {prompt}", flush=True)
            print("[initialization] LLM domain recommendation request started", flush=True)
            # 领域预选只需要结构化 JSON，不需要推理过程；仅在这一步关闭思考模式，
            # 不改变全局模型配置，也不依赖具体模型名称。extra_body 会由 OpenAI
            # 兼容客户端原样传给供应商接口。
            raw = asyncio.run(build_llm().generate(
                prompt,
                temperature=0.2,
                max_tokens=4096,
                extra_body={"thinking": {"type": "disabled"}},
            ))
            print(f"[initialization] LLM domain recommendation raw: {raw.text}", flush=True)
            recommended = json.loads(raw.text[raw.text.find("["):raw.text.rfind("]") + 1])
            valid_domain_ids = {str(item.get("id")) for item in domains if item.get("id")}
            invalid_recommendations = [
                item for item in recommended
                if not isinstance(item, dict) or str(item.get("domain_id")) not in valid_domain_ids
            ]
            if invalid_recommendations:
                print(
                    "[initialization] invalid LLM domain recommendations filtered: "
                    + json.dumps(invalid_recommendations, ensure_ascii=False),
                    flush=True,
                )
            recommended = [
                item for item in recommended
                if isinstance(item, dict) and str(item.get("domain_id")) in valid_domain_ids
            ]
            print(f"[initialization] LLM domain recommendations: {json.dumps(recommended, ensure_ascii=False)}", flush=True)
        except Exception as exc:
            print(f"[initialization] LLM domain recommendation error: {type(exc).__name__}: {exc!r}", flush=True)
            recommended = []
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
        print(f"[initialization] save step={step} session={session_id}", flush=True)
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

    async def preview_profile(self, session_id: str, user_id: str | None = None) -> dict[str, Any]:
        """调用真实 LLM 生成初始画像草稿并保存为待确认状态。"""
        session = self.get(session_id, user_id=user_id)
        if not session:
            raise ValueError("初始化会话不存在")
        data = session.get("input_data") or {}
        draft: dict[str, Any] = {"summary": "根据你的知乎资料与答题结果生成的初始画像", "style": data.get("style", {}), "interests": [], "expertise": [], "opinions": [], "behaviors": []}
        try:
            value = await _generate_profile_draft(data)
            if value:
                nested = value.get("profile") if isinstance(value.get("profile"), dict) else value
                draft.update(nested)
        except Exception as exc:
            print(f"[initialization] LLM preview error: {type(exc).__name__}: {exc!r}", flush=True)
        with connect() as db:
            db.execute("UPDATE avatar_initialization_sessions SET status='review',current_step='profile_review',generated_profile=%s,updated_at=now() WHERE id=%s", (Jsonb(draft), session_id))
        return {"session_id": session_id, "status": "review", "profile": draft}

    @staticmethod
    def _find_user(db, user_id: str):
        """查找内部 UUID 或登录系统 external_id，避免向 uuid 列传入任意字符串。"""
        try:
            value = str(UUID(str(user_id)))
        except (ValueError, TypeError, AttributeError):
            return db.execute("SELECT id FROM users WHERE external_id=%s AND deleted_at IS NULL", (str(user_id),)).fetchone()
        return db.execute("SELECT id FROM users WHERE id=%s AND deleted_at IS NULL", (value,)).fetchone()

    async def complete(self, session_id: str, identity: dict[str, Any], profile: dict[str, Any] | None = None, user_id: str | None = None) -> dict[str, Any]:
        """根据已保存结果创建初始画像版本并完成初始化。"""
        print(f"[initialization] complete session={session_id}", flush=True)
        session = self.get(session_id, user_id=user_id)
        if not session:
            raise ValueError("初始化会话不存在")
        data = session.get("input_data") or {}
        # 用户确认时以编辑后的画像为准，保留原始问卷数据用于审计和记忆生成。
        confirmed_profile = profile if isinstance(profile, dict) else (session.get("generated_profile") or {})
        if confirmed_profile:
            identity = {**identity, "summary": confirmed_profile.get("summary") or identity.get("summary"), "extra": {**(identity.get("extra") or {}), "llm_profile": confirmed_profile}}
            data = {**data, "style": confirmed_profile.get("style") or data.get("style") or {}}
        personality = data.get("personality", {})
        # API may receive raw answers or an already scored assessment result.
        if isinstance(personality, dict) and "answers" in personality and "scores" not in personality:
            personality = score_assessment(personality["answers"], personality.get("assessment_id", f"assessment_{uuid4().hex}"), personality.get("notes"))
        elif isinstance(personality, dict) and "scores" in personality:
            personality = {**personality, "model_name": personality.get("model_name", personality.get("model", "big_five")), "inference_source": personality.get("inference_source", personality.get("source", "self_report")), "status": personality.get("status") if personality.get("status") in {"confirmed", "unconfirmed", "rejected"} else "unconfirmed"}
        if isinstance(personality, dict):
            personality["status"] = personality.get("status") if personality.get("status") in {"confirmed", "unconfirmed", "rejected"} else "unconfirmed"
        # 综合知乎资料与全部答题结果生成最终画像摘要；确认草稿存在时直接复用，避免重复调用模型。
        try:
            generated = confirmed_profile or (session.get("generated_profile") or {})
            if not generated:
                generated = await _generate_profile_draft(data) or {}
            if isinstance(generated, dict):
                draft = generated.get("profile") if isinstance(generated.get("profile"), dict) else generated
                identity = {**identity, "summary": draft.get("summary") or identity.get("summary"), "extra": {**(identity.get("extra") or {}), "llm_profile": draft}}
                print("[initialization] LLM final profile generated", flush=True)
        except Exception as exc:
            print(f"[initialization] LLM final profile error: {type(exc).__name__}: {exc!r}; using submitted data", flush=True)
            pass
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
        # 将用户确认后的画像分类字段写入记忆表，仓储层会为每条记录创建 outbox，随后同步到 Chroma。
        profile_memory_map = (("interests", "interest", "shallow"), ("expertise", "expertise", "middle"), ("opinions", "opinion", "middle"), ("behaviors", "behavior", "middle"))
        for field, memory_type, level in profile_memory_map:
            values = confirmed_profile.get(field) if isinstance(confirmed_profile, dict) else None
            if isinstance(values, dict):
                values = [{"topic": key, "content": value} for key, value in values.items()]
            if not isinstance(values, list):
                continue
            for value in values:
                if isinstance(value, dict):
                    content = value.get("content") or value.get("label") or value.get("name") or json.dumps(value, ensure_ascii=False)
                    topic = value.get("topic") or value.get("name") or field
                    structured = value
                else:
                    content, topic, structured = str(value), field, {"value": value}
                apply({"memory_type": memory_type, "level": level, "topic": str(topic), "content": str(content), "structured_data": structured}, f"propose_{memory_type}_memory", "")
        # Return the actually active version after dynamic memories were merged.
        result["version_id"] = version_id
        with connect() as db:
            db.execute("UPDATE avatar_initialization_sessions SET status='completed',current_step='completed',generated_profile=%s,completed_at=now(),updated_at=now() WHERE id=%s", (Jsonb(result), session_id))
        print(f"[initialization] completed avatar_id={avatar_id} version_id={version_id}", flush=True)
        return result
