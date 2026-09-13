"""认证领域服务。

身份来源：知乎 OAuth。本平台不维护账号密码，
用户首次授权时按知乎 uid 自动建档。
"""

from __future__ import annotations

from typing import Any

from . import repository


class AuthError(Exception):
    """认证失败。code 供 API 层映射为错误响应。"""

    def __init__(self, code: str, message: str, status_code: int = 401):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def login_with_zhihu_profile(profile: dict[str, Any]) -> dict[str, Any]:
    """知乎授权成功后建档或更新，返回平台用户记录。"""
    try:
        return repository.upsert_zhihu_user(profile)
    except ValueError:
        raise AuthError("ZHIHU_UID_MISSING", "知乎未返回有效用户标识", 502) from None


def get_current_user(user_id: str) -> dict[str, Any]:
    user = repository.get_by_id(user_id)
    if user is None:
        # 会话有效但用户档案已被删除
        raise AuthError("USER_NOT_FOUND", "用户不存在", 401)
    return user


def to_me_payload(user: dict[str, Any], zhihu_token_valid: bool = True) -> dict[str, Any]:
    """整理 GET /api/v1/me 的 data。

    字段与 integration.md 一致，额外带上昵称头像供前端直接展示。
    绝不返回知乎 access_token。
    """
    return {
        "user_id": user["user_id"],
        "avatar_id": user.get("avatar_id"),
        "avatar_status": user.get("avatar_status", "not_created"),
        # 授权已断开或 token 过期时，前端应引导重新授权
        "zhihu_connected": bool(user.get("zhihu_connected")) and zhihu_token_valid,
        "zhihu": {
            "fullname": user.get("fullname", ""),
            "avatar_url": user.get("avatar_url", ""),
            "headline": user.get("headline", ""),
        },
    }


def disconnect_zhihu(user_id: str) -> None:
    repository.set_zhihu_disconnected(user_id)
