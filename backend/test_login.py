"""登录链路自测脚本（不调用真实知乎接口）。

用 Mock 替换知乎 OAuth 的两个网络调用，验证：
  state 安全校验 / 建档 / Cookie / 会话 / uid 精度 / 敏感字段泄露

运行：
    cd D:\\program\\Zhihu\\backend
    python test_login.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import urllib.parse as up
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# 必须在 import app 之前设置，避免污染真实数据文件
_STORE = Path(tempfile.gettempdir()) / "twinloop_test_users.json"
_STORE.unlink(missing_ok=True)
os.environ.update({
    "ZHIHU_OAUTH_APP_ID": "468",
    "ZHIHU_OAUTH_APP_KEY": "mock_key_for_test",
    "ZHIHU_OAUTH_REDIRECT_URI": "http://127.0.0.1:8000/api/v1/sources/zhihu/callback",
    "TWINLOOP_USER_STORE": str(_STORE),
})

from fastapi.testclient import TestClient  # noqa: E402

from app.consent import zhihu_oauth  # noqa: E402
from app.main import app  # noqa: E402

# 取一个超出 JavaScript 安全整数范围的真实量级 uid，用于精度验证
BIG_UID = 969570047710216200
MOCK_TOKEN = "mock_access_token_should_never_leak"

zhihu_oauth.exchange_token = lambda code: {
    "access_token": MOCK_TOKEN, "token_type": "Bearer", "expires_in": 3600,
}
zhihu_oauth.fetch_user_profile = lambda token: {
    "uid": BIG_UID,
    "hash_id": "0e4f7a11",
    "fullname": "测试用户",
    "avatar_path": "https://picx.zhimg.com/example.jpg",
    "headline": "一句话介绍",
}

_passed, _failed = 0, 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global _passed, _failed
    if condition:
        _passed += 1
        print(f"  [PASS] {name}")
    else:
        _failed += 1
        print(f"  [FAIL] {name}  {detail}")


def get_state(client: TestClient) -> str:
    """发起授权并从 authorization_url 中取出 state。"""
    url = client.post("/api/v1/sources/zhihu/connect", json={}).json()["data"]["authorization_url"]
    return up.parse_qs(up.urlparse(url).query)["state"][0]


def main() -> int:
    c = TestClient(app, follow_redirects=False)

    print("\n[1] 未登录访问 /api/v1/me")
    r = c.get("/api/v1/me")
    check("返回 401", r.status_code == 401, f"实际 {r.status_code}")
    check("错误码为 NOT_AUTHENTICATED",
          r.json().get("error", {}).get("code") == "NOT_AUTHENTICATED")

    print("\n[2] 发起授权 POST /api/v1/sources/zhihu/connect")
    r = c.post("/api/v1/sources/zhihu/connect", json={"scopes": ["profile", "answers"]})
    check("返回 200", r.status_code == 200, f"实际 {r.status_code}")
    data = r.json().get("data", {})
    url = data.get("authorization_url", "")
    check("授权地址指向知乎", url.startswith("https://openapi.zhihu.com/authorize"))
    check("携带 app_id", "app_id=468" in url)
    check("携带 state", "state=" in url)
    check("返回 state_id", bool(data.get("state_id")))

    print("\n[3] state 安全校验")
    r = c.get("/api/v1/sources/zhihu/callback?authorization_code=x")
    check("缺少 state 被拒", r.status_code == 400 and
          r.json()["error"]["code"] == "STATE_MISSING")

    r = c.get("/api/v1/sources/zhihu/callback?authorization_code=x&state=forged_by_attacker")
    check("伪造 state 被拒", r.status_code == 400 and
          r.json()["error"]["code"] == "STATE_INVALID")

    s = get_state(c)
    c.get(f"/api/v1/sources/zhihu/callback?authorization_code=good&state={s}")
    r = c.get(f"/api/v1/sources/zhihu/callback?authorization_code=good&state={s}")
    check("state 重放被拒", r.status_code == 400 and
          r.json()["error"]["code"] == "STATE_INVALID")

    print("\n[4] 完整授权回调")
    c2 = TestClient(app, follow_redirects=False)
    s = get_state(c2)
    r = c2.get(f"/api/v1/sources/zhihu/callback?authorization_code=good&state={s}")
    check("回调返回 302", r.status_code == 302, f"实际 {r.status_code}")
    sc = r.headers.get("set-cookie", "")
    check("下发会话 Cookie", "twinloop_session" in sc)
    check("Cookie 带 HttpOnly", "httponly" in sc.lower())
    check("Cookie 带 SameSite", "samesite" in sc.lower())

    print("\n[5] 登录后读取 /api/v1/me")
    r = c2.get("/api/v1/me")
    check("返回 200", r.status_code == 200, f"实际 {r.status_code}")
    d = r.json().get("data", {})
    check("包含 user_id", bool(d.get("user_id")))
    check("包含 avatar_id 字段", "avatar_id" in d)
    check("avatar_status 为 not_created", d.get("avatar_status") == "not_created")
    check("zhihu_connected 为 true", d.get("zhihu_connected") is True)
    check("返回知乎昵称", d.get("zhihu", {}).get("fullname") == "测试用户")

    print("\n[6] 敏感字段防泄露")
    body = r.text
    check("响应不含 access_token 值", MOCK_TOKEN not in body)
    check("响应不含 access_token 字段名", "access_token" not in body)

    print("\n[7] uid 精度（int64 超出 JS 安全范围）")
    saved = json.loads(_STORE.read_text(encoding="utf-8"))["users"][0]["zhihu_uid"]
    check("以字符串保存", isinstance(saved, str), f"实际 {type(saved).__name__}")
    check("数值无损", saved == str(BIG_UID), f"期望 {BIG_UID} 实际 {saved}")

    print("\n[8] 同一知乎账号二次授权复用档案")
    uid1 = d["user_id"]
    c3 = TestClient(app, follow_redirects=False)
    s = get_state(c3)
    c3.get(f"/api/v1/sources/zhihu/callback?authorization_code=good&state={s}")
    uid2 = c3.get("/api/v1/me").json()["data"]["user_id"]
    check("user_id 一致", uid1 == uid2, f"{uid1} vs {uid2}")

    print("\n[9] 会话隔离与退出登录")
    check("新客户端未登录为 401", TestClient(app).get("/api/v1/me").status_code == 401)
    check("退出返回 200", c2.post("/api/v1/auth/logout", json={}).status_code == 200)
    check("退出后 /me 为 401", c2.get("/api/v1/me").status_code == 401)

    print("\n" + "=" * 46)
    print(f"  通过 {_passed} 项，失败 {_failed} 项")
    print("=" * 46)
    _STORE.unlink(missing_ok=True)
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
