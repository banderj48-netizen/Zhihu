"""FastAPI 依赖：从会话 Cookie 解析当前用户。

前端不传 user_id，身份一律由服务端 Cookie 推导，防止越权伪造。
"""

from __future__ import annotations

from typing import Any

from fastapi import Depends, Request

from . import service, session


async def get_current_user(request: Request) -> dict[str, Any]:
    """要求已登录。未登录或会话过期抛 AuthError，由异常处理器转成 401。"""
    session_id = session.read_session_id(request)
    sess = session.get_session(session_id)
    if sess is None:
        raise service.AuthError("NOT_AUTHENTICATED", "未登录或会话已过期")
    return service.get_current_user(sess["user_id"])


async def get_optional_user(request: Request) -> dict[str, Any] | None:
    """允许匿名访问的场景使用。"""
    session_id = session.read_session_id(request)
    sess = session.get_session(session_id)
    if sess is None:
        return None
    try:
        return service.get_current_user(sess["user_id"])
    except service.AuthError:
        return None


CurrentUser = Depends(get_current_user)
OptionalUser = Depends(get_optional_user)
