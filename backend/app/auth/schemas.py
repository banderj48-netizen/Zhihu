"""认证与授权模块的请求与响应模型。

遵循 backend/app/integration.md 的通用约定：
- 写请求携带 request_id
- 响应统一包含 request_id 以及 data 或 error
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

AvatarStatus = Literal["not_created", "processing", "review", "ready", "paused"]


def new_request_id() -> str:
    return "req_" + uuid4().hex


# --------------------------------------------------------------------------
# 请求体
# --------------------------------------------------------------------------


class ConnectRequest(BaseModel):
    """POST /api/v1/sources/zhihu/connect"""

    scopes: list[str] = Field(default_factory=lambda: ["profile", "answers"])
    request_id: str | None = None


class LogoutRequest(BaseModel):
    request_id: str | None = None


# --------------------------------------------------------------------------
# 响应体
# --------------------------------------------------------------------------


class ZhihuBrief(BaseModel):
    fullname: str = ""
    avatar_url: str = ""
    headline: str = ""


class MeData(BaseModel):
    """GET /api/v1/me 的 data 部分。"""

    user_id: str
    avatar_id: str | None = None
    avatar_status: AvatarStatus = "not_created"
    zhihu_connected: bool = False
    zhihu: ZhihuBrief = Field(default_factory=ZhihuBrief)


class ConnectData(BaseModel):
    authorization_url: str
    state_id: str


class ErrorBody(BaseModel):
    """错误响应至少包含 code、message、retryable、request_id。"""

    code: str
    message: str
    retryable: bool = False


def ok(data: Any, request_id: str) -> dict[str, Any]:
    """成功响应：只返回 data，不返回 error。"""
    return {"request_id": request_id, "data": data}


def fail(code: str, message: str, request_id: str, retryable: bool = False) -> dict[str, Any]:
    """失败响应：只返回 error，不返回 data。"""
    return {
        "request_id": request_id,
        "error": {"code": code, "message": message, "retryable": retryable},
    }
