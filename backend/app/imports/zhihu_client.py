"""知乎开放平台数据读取客户端。

身份模型（两种凭证职责不同，读取授权用户数据时必须同时提供）：
  Authorization: Bearer <access_secret>   鉴权"调用方是谁"，即本应用
  X-OAuth-Token: <oauth_access_token>     指明"当前代表哪个用户"
  X-Request-Timestamp: <unix 秒>          必填，缺失会鉴权失败

能力边界（重要）：
  列表接口只返回标题与摘要，不含正文全文。
  读取正文的 content_detail 接口只支持 Access Secret 所属账号本人，
  不支持通过 X-OAuth-Token 切换身份，因此第三方授权用户拿不到全文。
"""

from __future__ import annotations

import json
import os
import time
import socket
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

BASE_URL = "https://developer.zhihu.com"

# 开放平台 Access Secret，代表本应用作为调用方
ACCESS_SECRET = os.environ.get("ZHIHU_ACCESS_SECRET", "")

_TIMEOUT = 60

# 内容类型白名单，与开放平台一致
CONTENT_TYPES = {"all", "answer", "article", "zvideo", "pin", "question"}


class ZhihuDataError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 502, detail: Any = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.detail = detail


def is_configured() -> bool:
    return bool(ACCESS_SECRET)


# 业务 Code 到对外错误的映射
_CODE_MAP = {
    10001: ("INVALID_PARAMS", "请求参数错误或内容不可用", 400),
    20001: ("ZHIHU_AUTH_DENIED", "知乎授权失败或已过期，请重新授权", 401),
    30001: ("RATE_LIMITED", "调用频率超限，请稍后重试", 429),
    30002: ("QUOTA_EXCEEDED", "当日调用额度已用尽", 429),
    30003: ("RISK_REJECTED", "请求被风控拒绝", 403),
    90001: ("ZHIHU_SERVER_ERROR", "知乎服务异常", 502),
}


def _get(path: str, params: dict[str, Any], oauth_token: str) -> dict[str, Any]:
    if not ACCESS_SECRET:
        raise ZhihuDataError(
            "ACCESS_SECRET_NOT_CONFIGURED",
            "未配置 ZHIHU_ACCESS_SECRET，无法读取用户数据",
            500,
        )

    url = f"{BASE_URL}{path}?" + urllib.parse.urlencode(
        {k: v for k, v in params.items() if v is not None}
    )
    req = urllib.request.Request(url, method="GET", headers={
        "Authorization": "Bearer " + ACCESS_SECRET,
        "X-OAuth-Token": oauth_token,
        "X-Request-Timestamp": str(int(time.time())),
        "Content-Type": "application/json",
    })

    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                raw = resp.read().decode("utf-8", "replace")
                status = resp.status
            break
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            status = e.code
            break
        except (urllib.error.URLError, TimeoutError, socket.timeout, ConnectionError) as e:
            last_error = e
            print(f"[zhihu-api] GET {path} network attempt {attempt}/3 failed: {e!r}", flush=True)
            if attempt == 3:
                raise ZhihuDataError("NETWORK_ERROR", f"无法连接知乎开放平台: {e}", 502, repr(e)) from e
            time.sleep(float(attempt))

    try:
        data = json.loads(raw)
    except ValueError:
        raise ZhihuDataError("INVALID_RESPONSE", "知乎返回非 JSON 内容", 502, raw[:500]) from None

    print(f"[zhihu-api] GET {path} HTTP {status} raw={json.dumps(data, ensure_ascii=False, default=str)}", flush=True)
    code = data.get("Code")
    if code != 0:
        mapped = _CODE_MAP.get(code)
        if mapped:
            err_code, err_msg, http_status = mapped
            raise ZhihuDataError(
                err_code, data.get("Message") or err_msg, http_status,
                {"zhihu_code": code, "http_status": status},
            )
        raise ZhihuDataError(
            "ZHIHU_ERROR", data.get("Message") or "知乎接口返回错误", 502,
            {"zhihu_code": code, "http_status": status},
        )

    return data.get("Data") or {}


def fetch_contents(
    oauth_token: str,
    content_type: str = "all",
    limit: int = 20,
    offset: Any = 0,
    sort_field: str = "ts",
    sort_order: str = "desc",
) -> dict[str, Any]:
    """读取授权用户的创作列表（标题与摘要，不含正文）。"""
    if content_type not in CONTENT_TYPES:
        raise ZhihuDataError(
            "INVALID_CONTENT_TYPE",
            f"ContentType 必须是 {sorted(CONTENT_TYPES)} 之一", 400,
        )
    return _get("/api/v1/user/contents", {
        "ContentType": content_type,
        "Limit": max(1, min(int(limit), 50)),   # 服务端上限 50
        "Offset": offset,
        "SortField": sort_field,                 # ts 或 like_count
        "SortOrder": sort_order,                 # desc 或 asc
    }, oauth_token)


def fetch_followees(oauth_token: str, limit: int = 20, offset: Any = 0) -> dict[str, Any]:
    """读取授权用户的关注列表。"""
    return _get("/api/v1/user/followees", {
        "Limit": max(1, min(int(limit), 50)),
        "Offset": offset,
    }, oauth_token)


def fetch_favlists(oauth_token: str, limit: int = 20) -> dict[str, Any]:
    """读取授权用户的收藏夹列表。该接口没有 Offset。"""
    return _get("/api/v1/user/favlists", {
        "Limit": max(1, min(int(limit), 50)),
    }, oauth_token)


def fetch_favlist_contents(
    oauth_token: str, favlist_url_token: Any, limit: int = 20, offset: Any = 0
) -> dict[str, Any]:
    """读取指定收藏夹中的内容。"""
    return _get("/api/v1/user/favlist_contents", {
        "FavlistUrlToken": favlist_url_token,
        "Limit": max(1, min(int(limit), 50)),
        "Offset": offset,
    }, oauth_token)


def fetch_collections(oauth_token: str, limit: int = 20) -> dict[str, Any]:
    """读取近期收藏。无分页，不等于完整收藏历史。"""
    return _get("/api/v1/user/collections", {
        "Limit": max(1, min(int(limit), 50)),
    }, oauth_token)
