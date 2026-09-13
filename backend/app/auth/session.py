"""会话与 HttpOnly Cookie 管理。

职责边界：
- 浏览器只持有随机、不可预测的会话 ID，通过 HttpOnly Cookie 承载。
- 知乎 access_token 保存在服务端会话中，不进入前端和 Agent
  （见 auth/README.md 与 integration.md）。
- 本地开发使用进程内存储；多实例或 Serverless 部署需替换为 Redis 等共享存储。
"""

from __future__ import annotations

import os
import secrets
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Request, Response

COOKIE_NAME = os.environ.get("TWINLOOP_SESSION_COOKIE", "twinloop_session")

# 应用会话有效期，默认 7 天。与知乎 token 有效期相互独立。
SESSION_TTL_SECONDS = int(os.environ.get("TWINLOOP_SESSION_TTL", str(7 * 24 * 3600)))

# 本地开发走 http://127.0.0.1:8000，浏览器会忽略 Secure 属性，
# 因此按部署环境决定。生产必须置为 true（integration.md 要求 Secure Cookie）。
COOKIE_SECURE = os.environ.get("TWINLOOP_COOKIE_SECURE", "false").lower() == "true"

# OAuth 回调是顶层跳转，lax 可正常携带 Cookie
COOKIE_SAMESITE = os.environ.get("TWINLOOP_COOKIE_SAMESITE", "lax").lower()

_lock = threading.RLock()
_sessions: dict[str, dict[str, Any]] = {}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _purge_expired() -> None:
    now = _now()
    for sid in [s for s, v in _sessions.items() if v["expires_at"] <= now]:
        _sessions.pop(sid, None)


def create_session(
    user_id: str,
    zhihu_access_token: str,
    zhihu_token_expires_at: datetime | None = None,
) -> tuple[str, datetime]:
    """创建会话并在服务端保管知乎 token。返回 (session_id, 会话过期时间)。"""
    session_id = secrets.token_urlsafe(32)
    expires_at = _now() + timedelta(seconds=SESSION_TTL_SECONDS)
    with _lock:
        _purge_expired()
        _sessions[session_id] = {
            "user_id": user_id,
            "zhihu_access_token": zhihu_access_token,
            "zhihu_token_expires_at": zhihu_token_expires_at,
            "created_at": _now(),
            "expires_at": expires_at,
        }
    return session_id, expires_at


def get_session(session_id: str | None) -> dict[str, Any] | None:
    if not session_id:
        return None
    with _lock:
        sess = _sessions.get(session_id)
        if not sess:
            return None
        if sess["expires_at"] <= _now():
            _sessions.pop(session_id, None)
            return None
        return dict(sess)


def get_zhihu_token(session_id: str | None) -> str | None:
    """取出服务端保管的知乎 token，供 imports 模块调用开放平台接口。

    token 过期返回 None；调用方应停止读取并引导用户重新授权，
    不得降级为平台自有 Access Secret 的本人身份。
    """
    sess = get_session(session_id)
    if not sess:
        return None
    exp = sess.get("zhihu_token_expires_at")
    if exp and exp <= _now():
        return None
    return sess.get("zhihu_access_token")


def zhihu_token_valid(session_id: str | None) -> bool:
    return get_zhihu_token(session_id) is not None


def destroy_session(session_id: str | None) -> None:
    if not session_id:
        return
    with _lock:
        _sessions.pop(session_id, None)


def destroy_user_sessions(user_id: str) -> int:
    """踢掉某用户的全部会话，用于撤销知乎授权或删除分身。"""
    with _lock:
        targets = [s for s, v in _sessions.items() if v["user_id"] == user_id]
        for sid in targets:
            _sessions.pop(sid, None)
        return len(targets)


def read_session_id(request: Request) -> str | None:
    return request.cookies.get(COOKIE_NAME)


def set_session_cookie(response: Response, session_id: str) -> None:
    response.set_cookie(
        key=COOKIE_NAME,
        value=session_id,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,          # 前端 JS 读不到，防 XSS 窃取
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=COOKIE_NAME,
        path="/",
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
    )


def active_session_count() -> int:
    with _lock:
        _purge_expired()
        return len(_sessions)
