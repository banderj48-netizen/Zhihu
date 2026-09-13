"""认证路由：当前用户与退出登录。

登录入口不在这里——登录即知乎授权，见 consent/router.py。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from . import service, session
from .dependencies import get_current_user
from .schemas import LogoutRequest, new_request_id, ok

router = APIRouter(prefix="/api/v1", tags=["auth"])


def _rid(request: Request, body_request_id: str | None = None) -> str:
    """request_id 优先级：请求体 > 请求头 > 服务端生成。"""
    return body_request_id or request.headers.get("X-Request-Id") or new_request_id()


@router.get("/me")
async def me(request: Request, user=Depends(get_current_user)):
    """前端启动时调用，返回当前用户与分身状态。

    zhihu_connected 会同时考虑知乎 token 是否仍然有效：
    token 过期时返回 false，前端据此引导重新授权。
    """
    token_valid = session.zhihu_token_valid(session.read_session_id(request))
    return ok(service.to_me_payload(user, token_valid), _rid(request))


@router.post("/auth/logout")
async def logout(request: Request, body: LogoutRequest | None = None):
    """退出登录。幂等：未登录时同样返回 200。

    只清除本地会话，不撤销知乎侧授权。
    """
    rid = _rid(request, body.request_id if body else None)
    session.destroy_session(session.read_session_id(request))

    resp = JSONResponse(status_code=200, content=ok({"logged_out": True}, rid))
    session.clear_session_cookie(resp)
    return resp
