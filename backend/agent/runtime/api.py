"""数字分身初始化、对话和反馈的最小 FastAPI 接口。"""
from __future__ import annotations

from typing import Any, Literal
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from agent.runtime.initialization import InitializationService
from agent.runtime.mind_reading import MindReadingService
from agent.runtime.chat_groups import ChatGroupService

router = APIRouter(prefix="/v1/twin", tags=["digital-twin"])
_initializations = InitializationService()
_mind_reading = MindReadingService()
_chat_groups = ChatGroupService()


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
def count_chat_groups(status: str | None = None, x_user_id: str | None = Header(default=None)):
    """统计当前用户参与的聊天组数量。"""
    return {"count": _chat_groups.count_my_chat_groups(x_user_id or "local-demo-user", status=status)}


@router.get("/chat-groups")
def list_chat_groups(page: int = 1, page_size: int = 20, status: str | None = None, x_user_id: str | None = Header(default=None)):
    """分页查询当前用户参与的聊天组。"""
    try:
        return _chat_groups.list_my_chat_groups(x_user_id or "local-demo-user", page=page, page_size=page_size, status=status)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/chat-groups/{chat_no}/messages")
def get_chat_group_messages(chat_no: str, x_user_id: str | None = Header(default=None)):
    """查询指定聊天组的完整消息并执行用户归属校验。"""
    value = _chat_groups.get_chat_group_messages(x_user_id or "local-demo-user", chat_no)
    if not value:
        raise HTTPException(404, "聊天记录不存在")
    return value
