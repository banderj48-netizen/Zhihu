"""知乎 OAuth 协议客户端。

只负责与知乎开放平台通信，不涉及会话与用户建档。

凭证职责（三者不可混用）：
  app_id        应用标识，可公开
  app_key       应用密钥，仅后端换 token 时使用
  access_token  代表已授权的知乎用户
  access_secret 开放平台调用方凭证，读取用户数据时与 access_token 同时提供

已确认的协议偏差（务必保留）：
  1. 回调参数名为 authorization_code，不是 code
  2. 但换 token 时表单字段仍叫 code
  3. 响应业务字段 code=20000 表示成功，不可当错误
  4. 只返回 access_token 与 expires_in，没有 refresh token
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

APP_ID = os.environ.get("ZHIHU_OAUTH_APP_ID", "468")
APP_KEY = os.environ.get("ZHIHU_OAUTH_APP_KEY", "1edca288684b4838a8beb643b7b74a12")
REDIRECT_URI = os.environ.get("ZHIHU_OAUTH_REDIRECT_URI", "http://127.0.0.1:8000/api/v1/sources/zhihu/callback")

AUTHORIZE_URL = "https://openapi.zhihu.com/authorize"
TOKEN_URL = "https://openapi.zhihu.com/access_token"
USERINFO_URL = "https://openapi.zhihu.com/user"

_TIMEOUT = 20


class ZhihuOAuthError(Exception):
    """知乎 OAuth 调用失败。"""

    def __init__(self, code: str, message: str, detail: Any = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail


def is_configured() -> bool:
    return bool(APP_ID and APP_KEY and REDIRECT_URI)


def build_authorize_url(state: str) -> str:
    """构造授权页地址。state 由 consent.service 生成并保管。"""
    if not APP_ID or not REDIRECT_URI:
        raise ZhihuOAuthError("OAUTH_NOT_CONFIGURED", "缺少 APP_ID 或 REDIRECT_URI")
    params = {
        "redirect_uri": REDIRECT_URI,   # 必须与赛事页面登记值逐字符一致
        "app_id": APP_ID,
        "response_type": "code",
        "state": state,
    }
    return AUTHORIZE_URL + "?" + urllib.parse.urlencode(params)


def _request_json(req: urllib.request.Request) -> tuple[int, Any]:
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            raw = resp.read().decode("utf-8", "replace")
            status = resp.status
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        status = e.code
    except Exception as e:  # 网络层失败
        raise ZhihuOAuthError("NETWORK_ERROR", "无法连接知乎开放平台", str(e)) from e

    try:
        return status, json.loads(raw)
    except ValueError:
        raise ZhihuOAuthError(
            "INVALID_RESPONSE", "知乎返回非 JSON 内容", raw[:500]
        ) from None


def exchange_token(authorization_code: str) -> dict[str, Any]:
    """用 authorization_code 换 access_token。

    注意 redirect_uri 必须与发起授权时完全一致，否则返回
    Invalid Redirect URI。
    """
    if not is_configured():
        raise ZhihuOAuthError("OAUTH_NOT_CONFIGURED", "知乎 OAuth 配置不完整")

    form = urllib.parse.urlencode({
        "app_id": APP_ID,
        "app_key": APP_KEY,
        "grant_type": "authorization_code",
        "redirect_uri": REDIRECT_URI,
        "code": authorization_code,     # 表单字段名是 code
    }).encode("utf-8")

    req = urllib.request.Request(
        TOKEN_URL, data=form, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    status, data = _request_json(req)

    # 成功判定以 access_token 是否存在为准；code=20000 是成功标记
    token = isinstance(data, dict) and data.get("access_token")
    if not token:
        raise ZhihuOAuthError(
            "TOKEN_EXCHANGE_FAILED",
            (data or {}).get("data") if isinstance(data, dict) else "换取 token 失败",
            {"status": status, "response": data},
        )
    return data


def fetch_user_profile(access_token: str) -> dict[str, Any]:
    """获取授权用户基础信息。该接口只需 OAuth token。"""
    req = urllib.request.Request(
        USERINFO_URL, method="GET",
        headers={"Authorization": "Bearer " + access_token},
    )
    status, data = _request_json(req)

    # 不能只凭 HTTP 200 判成功，必须确认拿到有效用户标识。
    # 历史错误示例：HTTP 200 + {"code":404,"data":"User don't exist"}
    if not isinstance(data, dict) or not (data.get("uid") or data.get("hash_id")):
        raise ZhihuOAuthError(
            "USERINFO_FAILED", "未获取到有效的知乎用户标识",
            {"status": status, "response": data},
        )
    return data
