"""数字分身初始化、对话和反馈的最小 FastAPI 接口。"""
from __future__ import annotations

from typing import Any, Literal
import asyncio
import json
import os
from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from agent.runtime.initialization import InitializationService
from agent.runtime.mind_reading import MindReadingService
from agent.runtime.chat_groups import ChatGroupService
from agent.runtime.presence import PresenceService
from agent.runtime.matching import AvatarMatcher
from agent.runtime.dialogue import run_agent_dialogue
from agent.runtime.dialogue_manager import DialogueManager
from app.auth import session as auth_session

router = APIRouter(prefix="/v1/twin", tags=["digital-twin"])
_initializations = InitializationService()
_mind_reading = MindReadingService()
_chat_groups = ChatGroupService()
_presence = PresenceService()


class _EmptyVector:
    """Chroma 不可用时的安全空适配器；PostgreSQL 事实记录仍正常工作。"""
    async def search(self, collection: str, query_text: str, *, where=None, limit: int = 20):
        """不返回向量候选。"""
        return []

    async def upsert(self, collection: str, ids, documents, metadatas):
        """忽略向量写入，避免阻断聊天。"""
        return None

    async def delete(self, collection: str, ids):
        """忽略向量删除。"""
        return None


async def _default_runner(**kwargs: Any):
    """使用现有 Builder、检索服务和聊天仓储运行一次双 Agent 对话。"""
    from db.database import connect
    from agent.retrieval.service import PostgresRetrievalRepository, build_context
    from agent.runtime.model_builder import build_llm, build_evaluator_llm
    from agent.runtime.evaluator import DialogueEvaluator
    from agent.runtime.push_gateway import NoopMatchPushGateway

    llm_a = build_llm()
    llm_b = build_llm()
    context_repo = PostgresRetrievalRepository(connect)
    async def context_builder(user_id: str, question: str, *, conversation_id: str | None = None):
        """显式组装固定画像与混合检索上下文。"""
        return await build_context(user_id, question, context_repo, _EmptyVector(), conversation_id=conversation_id)
    evaluator = None
    try:
        evaluator = DialogueEvaluator(build_evaluator_llm())
    except Exception:
        evaluator = None
    from agent.profile.chat_repository import ChatRepository
    return await run_agent_dialogue(llm_a=llm_a, llm_b=llm_b, context_builder=context_builder, chat_repository=ChatRepository(), evaluator=evaluator, push_gateway=NoopMatchPushGateway(), vector_store=_EmptyVector(), **kwargs)


_dialogues = DialogueManager(_default_runner, max_dialogues=int(os.getenv("MAX_AGENT_DIALOGUES", "10")), presence=_presence)


def _resolved_user(request: Request, header_user_id: str | None) -> str:
    """优先从 HttpOnly 会话 Cookie 解析用户，兼容本地测试的 X-User-Id。"""
    current = auth_session.get_session(auth_session.read_session_id(request))
    if current:
        return str(current["user_id"])
    return header_user_id or "local-demo-user"


class MatchRequest(BaseModel):
    """场景匹配请求；当前用户 avatar 始终由服务端确定为 A。"""
    scene_id: str
    match_mode: Literal["manual", "random", "llm"] = "random"
    target_avatar_id: str | None = None


class DialogueRequest(MatchRequest):
    """后台双 Agent 对话请求。"""
    initial_question: str | None = None
    max_rounds: int = Field(default=10, ge=1, le=10)


class InitCreate(BaseModel):
    """初始化创建参数。"""
    import_job_id: str | None = None


class InitStep(BaseModel):
    """初始化步骤负载。"""
    data: dict[str, Any] = Field(default_factory=dict)


class InitComplete(BaseModel):
    """完成初始化时用户填写的基础身份。"""
    identity: dict[str, Any] = Field(default_factory=dict)


@router.post("/initializations")
def create_initialization(body: InitCreate, x_user_id: str | None = Header(default=None)):
    """创建或恢复当前用户的唯一初始化会话。"""
    try:
        return _initializations.create(x_user_id or "local-demo-user", body.import_job_id)
    except Exception as exc:
        raise HTTPException(503, "初始化会话暂不可用") from exc


@router.get("/initializations/{session_id}")
def get_initialization(session_id: str):
    """读取初始化会话状态。"""
    value = _initializations.get(session_id)
    if not value:
        raise HTTPException(404, "初始化会话不存在")
    return value


@router.post("/initializations/{session_id}/{step}")
def save_initialization_step(session_id: str, step: str, body: InitStep):
    """保存性格、领域或问卷步骤。"""
    try:
        return _initializations.save_step(session_id, step, body.data)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/initializations/{session_id}/complete")
async def complete_initialization(session_id: str, body: InitComplete):
    """生成并激活初始画像。"""
    try:
        return await _initializations.complete(session_id, body.identity)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/mind-reading/{dialogue_run_id}")
def create_mind_reading(dialogue_run_id: str, body: dict[str, Any], x_user_id: str | None = Header(default=None)):
    """保存一条待用户选择的心灵感应题。"""
    avatar_id = str(body.get("avatar_id", ""))
    if not avatar_id:
        raise HTTPException(422, "avatar_id 不能为空")
    return _mind_reading.create_question(x_user_id or "local-demo-user", avatar_id, dialogue_run_id, body)


@router.post("/mind-reading/{question_id}/answer")
def answer_mind_reading(question_id: str, body: dict[str, str]):
    """提交心灵感应题选择。"""
    try:
        return _mind_reading.answer(question_id, body.get("option_id", ""))
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/chat-groups/count")
def count_chat_groups(request: Request, status: str | None = None, x_user_id: str | None = Header(default=None)):
    """统计当前用户参与的聊天组数量。"""
    return {"count": _chat_groups.count_my_chat_groups(_resolved_user(request, x_user_id), status=status)}


@router.get("/chat-groups")
def list_chat_groups(request: Request, page: int = 1, page_size: int = 20, status: str | None = None, x_user_id: str | None = Header(default=None)):
    """分页查询当前用户参与的聊天组。"""
    try:
        return _chat_groups.list_my_chat_groups(_resolved_user(request, x_user_id), page=page, page_size=page_size, status=status)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/chat-groups/{chat_no}/messages")
def get_chat_group_messages(chat_no: str, request: Request, x_user_id: str | None = Header(default=None)):
    """查询指定聊天组的完整消息并执行用户归属校验。"""
    value = _chat_groups.get_chat_group_messages(_resolved_user(request, x_user_id), chat_no)
    if not value:
        raise HTTPException(404, "聊天记录不存在")
    return value


def _my_avatar(user_id: str) -> dict[str, Any] | None:
    """读取当前用户唯一数字分身，防止前端伪造发起方。"""
    from db.database import connect
    with connect() as db:
        row = db.execute("SELECT id, user_id, display_name, summary FROM user_avatars WHERE user_id=%s AND status <> 'archived' LIMIT 1", (user_id,)).fetchone()
    return dict(row) if row else None


def _candidate_user(avatar_id: str) -> str:
    """根据候选 avatar 查询所属用户。"""
    from db.database import connect
    with connect() as db:
        row = db.execute("SELECT user_id FROM user_avatars WHERE id=%s AND status <> 'archived'", (avatar_id,)).fetchone()
    if not row:
        raise HTTPException(404, "目标看山不存在")
    return str(row["user_id"])


@router.get("/scenes")
def list_scenes():
    """返回可进入的小镇场景目录。"""
    return {"items": _presence.list_scenes()}


@router.get("/scenes/{scene_id}/avatars")
def list_scene_avatars(scene_id: str, x_user_id: str | None = Header(default=None)):
    """返回场景空闲候选，当前用户自己的 Agent 不会出现在候选中。"""
    me = _my_avatar(x_user_id or "local-demo-user")
    return {"scene_id": scene_id, "items": _presence.list_candidates(scene_id, exclude_avatar_id=str(me["id"]) if me else None)}


@router.post("/matches")
async def match_avatar(body: MatchRequest, request: Request, x_user_id: str | None = Header(default=None)):
    """按手动、随机或 LLM 模式选择 B；A 永远是当前登录用户的看山。"""
    user_id = _resolved_user(request, x_user_id)
    me = _my_avatar(user_id)
    if not me:
        raise HTTPException(409, "请先完成数字分身初始化")
    llm = None
    if body.match_mode == "llm":
        try:
            from agent.runtime.model_builder import build_llm
            llm = build_llm()
        except Exception:
            body.match_mode = "random"
    matcher = AvatarMatcher(lambda scene: _presence.list_candidates(scene, exclude_avatar_id=str(me["id"])), llm)
    try:
        candidate = await matcher.match(str(me["id"]), body.scene_id, body.match_mode, body.target_avatar_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"initiator": {"avatar_id": str(me["id"]), "user_id": user_id, "display_name": me.get("display_name")}, "invited": candidate, "scene_id": body.scene_id, "match_mode": body.match_mode}


@router.post("/dialogues", status_code=202)
async def start_dialogue(body: DialogueRequest, request: Request, x_user_id: str | None = Header(default=None)):
    """创建后台双 Agent 对话；服务端固定 A 为当前登录用户的 avatar。"""
    user_id = _resolved_user(request, x_user_id)
    me = _my_avatar(user_id)
    if not me:
        raise HTTPException(409, "请先完成数字分身初始化")
    llm = None
    if body.match_mode == "llm":
        try:
            from agent.runtime.model_builder import build_llm
            llm = build_llm()
        except Exception:
            body.match_mode = "random"
    matcher = AvatarMatcher(lambda scene: _presence.list_candidates(scene, exclude_avatar_id=str(me["id"])), llm)
    try:
        candidate = await matcher.match(str(me["id"]), body.scene_id, body.match_mode, body.target_avatar_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    avatar_b = str(candidate["avatar_id"])
    user_b = _candidate_user(avatar_b)
    run_id = str(__import__("uuid").uuid4())
    _presence.ensure_presence(str(me["id"]), body.scene_id, {"display_name": me.get("display_name")})
    _presence.ensure_presence(avatar_b, body.scene_id, candidate.get("display_summary") or {})
    if not _presence.occupy(str(me["id"]), body.scene_id, "") or not _presence.occupy(avatar_b, body.scene_id, ""):
        _presence.release(str(me["id"]), body.scene_id)
        _presence.release(avatar_b, body.scene_id)
        raise HTTPException(409, "目标看山刚刚被其他用户占用")
    try:
        from db.database import connect
        with connect() as db:
            db.execute("""INSERT INTO agent_world_days(user_id,day_no,selected_scene_id,day_status)
                VALUES(%s,1,%s,'running') ON CONFLICT(user_id) DO UPDATE SET selected_scene_id=%s,day_status='running',updated_at=now()""", (user_id, body.scene_id, body.scene_id))
    except Exception:
        # 日状态表是可选迁移；对话本身仍可运行。
        pass
    try:
        await _dialogues.start(run_id=run_id, avatar_a_id=str(me["id"]), avatar_b_id=avatar_b, user_id_a=user_id, user_id_b=user_b, scene_id=body.scene_id, initial_question=body.initial_question, topic_mode="shared_first", max_rounds=body.max_rounds)
    except Exception:
        _presence.release(str(me["id"]), body.scene_id)
        _presence.release(avatar_b, body.scene_id)
        raise
    return {"run_id": run_id, "avatar_a_id": str(me["id"]), "avatar_b_id": avatar_b, "scene_id": body.scene_id, "status": "queued"}


@router.get("/dialogues/{run_id}")
def get_dialogue(run_id: str, x_user_id: str | None = Header(default=None)):
    """读取后台对话状态和事件摘要。"""
    value = _dialogues.status(run_id)
    if value.get("result") and x_user_id:
        from db.database import connect
        with connect() as db:
            owner = db.execute("SELECT 1 FROM agent_dialogue_runs WHERE id=%s AND (user_a_id=%s OR user_b_id=%s)", (run_id, x_user_id, x_user_id)).fetchone()
        if not owner:
            raise HTTPException(404, "对话不存在")
    return value


@router.get("/dialogues/{run_id}/events")
async def dialogue_events(run_id: str, last_event_id: str | None = Header(default=None, alias="Last-Event-ID"), last_event_id_query: str | None = Query(default=None, alias="last_event_id")):
    """以 SSE 推送实时消息、轮次、评判和终态事件。"""
    if run_id not in _dialogues.events:
        raise HTTPException(404, "对话不存在")
    async def stream():
        """将管理器事件编码为浏览器 EventSource 可消费的格式。"""
        async for event in _dialogues.subscribe(run_id, last_event_id or last_event_id_query):
            yield f"id: {event.get('event_id')}\nevent: {event.get('event')}\ndata: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/dialogues/{run_id}/cancel")
async def cancel_dialogue(run_id: str, x_user_id: str | None = Header(default=None)):
    """请求协作式取消对话，并由运行函数写入 cancelled 终态。"""
    if not await _dialogues.cancel(run_id):
        raise HTTPException(404, "对话不存在或已结束")
    return {"run_id": run_id, "status": "cancelling"}


@router.post("/dialogues/{run_id}/advance-day")
def advance_day(run_id: str, request: Request, x_user_id: str | None = Header(default=None)):
    """对话终态后推进当前用户天数并回到地图选择状态。"""
    from db.database import connect
    user_id = _resolved_user(request, x_user_id)
    with connect() as db:
        row = db.execute("SELECT status FROM agent_dialogue_runs WHERE id=%s AND user_a_id=%s", (run_id, user_id)).fetchone()
        if not row or row["status"] not in {"completed", "cancelled", "evaluation_failed", "failed"}:
            raise HTTPException(409, "对话尚未结束")
        value = db.execute("""INSERT INTO agent_world_days(user_id,day_no,selected_scene_id,last_dialogue_run_id,day_status)
            VALUES(%s,1,NULL,%s,'selecting') ON CONFLICT(user_id) DO UPDATE SET day_no=agent_world_days.day_no+1,selected_scene_id=NULL,last_dialogue_run_id=%s,day_status='selecting',updated_at=now() RETURNING day_no""", (user_id, run_id, run_id)).fetchone()
    return {"user_id": user_id, "day_no": value["day_no"], "day_status": "selecting"}


@router.post("/chat-groups/{chat_no}/read")
def mark_chat_group_read(chat_no: str, request: Request, x_user_id: str | None = Header(default=None)):
    """将当前用户参与的已处理聊天组标记为已读。"""
    if not _chat_groups.mark_read(_resolved_user(request, x_user_id), chat_no):
        raise HTTPException(404, "聊天记录不存在")
    return {"chat_no": chat_no, "read": True}
