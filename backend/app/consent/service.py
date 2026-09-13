"""知乎授权领域服务。

负责 OAuth state 的生成、校验与原子消费，以及授权完成后的用户建档编排。
所有下游数据读取必须经过这里的授权结果。
"""

from __future__ import annotations

import secrets
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from . import zhihu_oauth

# state 有效期：够用户完成登录授权，又不长期滞留
STATE_TTL_SECONDS = 600

_lock = threading.RLock()
_pending_states: dict[str, dict[str, Any]] = {}


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ConsentError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400, detail: Any = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.detail = detail


def _purge_expired() -> None:
    now = _now()
    for s in [k for k, v in _pending_states.items() if v["expires_at"] <= now]:
        _pending_states.pop(s, None)


def create_state(scopes: list[str] | None = None) -> tuple[str, str]:
    """生成不可预测的 state 并登记。返回 (state, state_id)。

    state 仅用于关联本次登录请求，不承载 app_key、token 或用户隐私。
    """
    state = secrets.token_urlsafe(32)
    state_id = "state_" + secrets.token_hex(8)
    with _lock:
        _purge_expired()
        _pending_states[state] = {
            "state_id": state_id,
            "scopes": scopes or ["profile"],
            "created_at": _now(),
            "expires_at": _now() + timedelta(seconds=STATE_TTL_SECONDS),
        }
    return state, state_id


def consume_state(state: str | None) -> dict[str, Any]:
    """原子校验并消费 state。

    pop 即消费，天然防重放。缺失、未知、已用过或过期一律拒绝。
    """
    if not state:
        raise ConsentError("STATE_MISSING", "缺少 state 参数", 400)
    with _lock:
        entry = _pending_states.pop(state, None)
    if entry is None:
        raise ConsentError("STATE_INVALID", "state 无效或已被使用", 400)
    if entry["expires_at"] <= _now():
        raise ConsentError("STATE_EXPIRED", "授权请求已过期，请重新发起", 400)
    return entry


def build_authorization(scopes: list[str] | None = None) -> dict[str, Any]:
    """创建知乎授权地址，对应 POST /api/v1/sources/zhihu/connect。"""
    if not zhihu_oauth.is_configured():
        raise ConsentError(
            "OAUTH_NOT_CONFIGURED",
            "知乎 OAuth 未配置，请设置 ZHIHU_OAUTH_APP_ID / APP_KEY / REDIRECT_URI",
            500,
        )
    state, state_id = create_state(scopes)
    return {
        "authorization_url": zhihu_oauth.build_authorize_url(state),
        "state_id": state_id,
    }


def complete_authorization(authorization_code: str, state: str) -> dict[str, Any]:
    """回调处理：先校验 state，再换 token，最后取用户资料。

    顺序不可调换——state 校验必须发生在任何 token 交换之前。
    """
    entry = consume_state(state)

    if not authorization_code:
        raise ConsentError("CODE_MISSING", "回调缺少 authorization_code", 400)

    try:
        token_data = zhihu_oauth.exchange_token(authorization_code)
        access_token = token_data["access_token"]
        profile = zhihu_oauth.fetch_user_profile(access_token)
    except zhihu_oauth.ZhihuOAuthError as exc:
        raise ConsentError(exc.code, exc.message or "知乎授权失败", 502, exc.detail) from exc

    expires_in = int(token_data.get("expires_in") or 0)
    token_expires_at = _now() + timedelta(seconds=expires_in) if expires_in else None

    return {
        "access_token": access_token,
        "token_expires_at": token_expires_at,
        "profile": profile,
        "scopes": entry.get("scopes", []),
    }
