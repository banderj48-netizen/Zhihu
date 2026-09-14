"""知乎授权路由：登录入口与 OAuth 回调。

登录流程（前端视角）：
  1. POST /api/v1/sources/zhihu/connect  -> 拿到 authorization_url
  2. 浏览器跳转到该地址，用户在知乎完成登录并确认授权
  3. 知乎回调 GET /api/v1/sources/zhihu/callback
  4. 后端校验 state -> 换 token -> 取资料 -> 建档 -> 种 HttpOnly Cookie
  5. 302 回前端，前端调用 GET /api/v1/me 读取身份
"""

from __future__ import annotations

import os
from urllib.parse import quote

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse

from ..auth import service as auth_service
from ..auth import session
from ..auth.schemas import ConnectRequest, fail, new_request_id, ok
from . import service

router = APIRouter(prefix="/api/v1/sources/zhihu", tags=["consent"])


def _rid(request: Request, body_request_id: str | None = None) -> str:
    return body_request_id or request.headers.get("X-Request-Id") or new_request_id()


def _callback_error(request: Request, exc: service.ConsentError, rid: str):
    """浏览器 OAuth 失败时回到前端认证页，接口调用仍返回标准 JSON 错误。"""
    if "text/html" in request.headers.get("accept", ""):
        frontend_url = os.environ.get("TWINLOOP_FRONTEND_URL", "http://127.0.0.1:3000/#intro")
        base_url = frontend_url.split("#", 1)[0].rstrip("/")
        return RedirectResponse(url=f"{base_url}/#auth?error={quote(exc.message)}", status_code=302)
    return JSONResponse(status_code=exc.status_code, content=fail(exc.code, exc.message, rid))


@router.post("/connect")
async def connect(request: Request, body: ConnectRequest | None = None):
    """创建知乎授权地址。后端负责 OAuth state、Token 和回调校验。"""
    rid = _rid(request, body.request_id if body else None)
    scopes = body.scopes if body else None
    try:
        data = service.build_authorization(scopes)
    except service.ConsentError as exc:
        return _callback_error(request, exc, rid)
    return ok(data, rid)


@router.get("/callback")
async def callback(
    request: Request,
    # 知乎实测回调参数名是 authorization_code；同时兼容 code 以防协议修订
    authorization_code: str | None = Query(default=None),
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
):
    """知乎 OAuth 回调。校验 state 后换 token 并建立登录会话。"""
    rid = _rid(request)
    auth_code = authorization_code or code

    try:
        # state 校验发生在任何 token 交换之前
        result = service.complete_authorization(auth_code or "", state or "")
    except service.ConsentError as exc:
        return JSONResponse(
            status_code=exc.status_code,
            content=fail(exc.code, exc.message, rid),
        )

    # 按知乎 uid 建档或更新资料
    try:
        user = auth_service.login_with_zhihu_profile(result["profile"])
    except auth_service.AuthError as exc:
        if "text/html" in request.headers.get("accept", ""):
            frontend_url = os.environ.get("TWINLOOP_FRONTEND_URL", "http://127.0.0.1:3000/#intro")
            base_url = frontend_url.split("#", 1)[0].rstrip("/")
            return RedirectResponse(url=f"{base_url}/#auth?error={quote(exc.message)}", status_code=302)
        return JSONResponse(status_code=exc.status_code, content=fail(exc.code, exc.message, rid))

    # 知乎 token 只存服务端会话，浏览器仅得到随机会话 ID
    session_id, _ = session.create_session(
        user_id=user["user_id"],
        zhihu_access_token=result["access_token"],
        zhihu_token_expires_at=result["token_expires_at"],
    )

    frontend_url = os.environ.get("TWINLOOP_FRONTEND_URL", "http://127.0.0.1:3000/")
    # 授权完成后统一回到新前端的 intro 首屏；保留显式配置中的 hash。
    if "#" not in frontend_url:
        frontend_url = frontend_url.rstrip("/") + "/#intro"
    resp = RedirectResponse(url=frontend_url, status_code=302)
    session.set_session_cookie(resp, session_id)
    return resp
