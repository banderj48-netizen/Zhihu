"""用户数据访问层。

身份模型：本平台没有独立账号密码体系，用户身份完全来自知乎 OAuth 授权。
知乎返回的 uid 是唯一外部身份标识，首次授权时自动建档（upsert）。

当前为本地开发实现：进程内存储 + JSON 文件持久化，接口保持仓储形态，
后续替换为 PostgreSQL 时只需重写本文件，不影响 service 与 router。

安全约定：知乎 access_token 只存服务端，不进入前端和 Agent。
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

def _pg_enabled() -> bool:
    return bool(os.getenv("DATABASE_URL"))

def _pg_upsert(profile: dict[str, Any]) -> dict[str, Any]:
    from db.database import connect
    zhihu_uid = str(profile.get("uid") or "").strip()
    with connect() as db:
        row = db.execute("""INSERT INTO public.users(external_id) VALUES(%s)
            ON CONFLICT(external_id) DO UPDATE SET updated_at=now()
            RETURNING id, external_id""", (zhihu_uid,)).fetchone()
        return {"user_id": str(row["id"]), "zhihu_uid": zhihu_uid,
                "zhihu_hash_id": profile.get("hash_id"),
                "fullname": profile.get("fullname") or "",
                "avatar_url": profile.get("avatar_path") or "",
                "headline": profile.get("headline", ""),
                "zhihu_connected": True}


def _pg_user_payload(*, user_id: str | None = None, zhihu_uid: str | None = None) -> dict[str, Any] | None:
    """从 PostgreSQL 读取登录用户及其数字分身状态。

    认证接口必须以 PostgreSQL 的 `user_avatars` 为分身状态事实源，
    不能只读取 `users`，否则初始化完成后前端仍会看到 `not_created`。
    `building` 映射为认证接口约定的 `processing`，归档分身按未创建处理。
    """
    from db.database import connect

    if user_id is not None:
        where_sql, value = "u.id::text=%s", str(user_id)
    elif zhihu_uid is not None:
        where_sql, value = "u.external_id=%s", str(zhihu_uid)
    else:
        raise ValueError("user_id 或 zhihu_uid 至少提供一个")
    with connect() as db:
        row = db.execute(
            f"""
            SELECT u.id, u.external_id, a.id AS avatar_id,
                   CASE
                       WHEN a.status = 'building' THEN 'processing'
                       WHEN a.status = 'archived' THEN 'not_created'
                       ELSE COALESCE(a.status, 'not_created')
                   END AS avatar_status
            FROM public.users u
            LEFT JOIN public.user_avatars a ON a.user_id = u.id
            WHERE {where_sql} AND u.deleted_at IS NULL
            ORDER BY a.updated_at DESC NULLS LAST
            LIMIT 1
            """,
            (value,),
        ).fetchone()
    if not row:
        return None
    return {
        "user_id": str(row["id"]),
        "zhihu_uid": row["external_id"],
        "avatar_id": str(row["avatar_id"]) if row["avatar_id"] else None,
        "avatar_status": row["avatar_status"] or "not_created",
        "zhihu_connected": True,
    }

_DATA_FILE = Path(
    os.environ.get(
        "TWINLOOP_USER_STORE",
        str(Path(__file__).resolve().parent / "_local_users.json"),
    )
)

_lock = threading.RLock()
_users: dict[str, dict[str, Any]] = {}      # user_id -> record
_zhihu_index: dict[str, str] = {}           # zhihu_uid -> user_id
_loaded = False


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load() -> None:
    global _loaded
    if _loaded:
        return
    with _lock:
        if _loaded:
            return
        if _DATA_FILE.exists():
            try:
                raw = json.loads(_DATA_FILE.read_text(encoding="utf-8"))
                for rec in raw.get("users", []):
                    _users[rec["user_id"]] = rec
                    if rec.get("zhihu_uid"):
                        _zhihu_index[str(rec["zhihu_uid"])] = rec["user_id"]
            except (ValueError, OSError, KeyError):
                _users.clear()
                _zhihu_index.clear()
        _loaded = True


def _flush() -> None:
    """原子写入：先写临时文件再替换，避免中断产生半截文件。"""
    try:
        _DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _DATA_FILE.with_suffix(".tmp")
        tmp.write_text(
            json.dumps({"users": list(_users.values())}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(_DATA_FILE)
    except OSError:
        pass


def get_by_id(user_id: str) -> dict[str, Any] | None:
    if _pg_enabled():
        return _pg_user_payload(user_id=user_id)
    _load()
    with _lock:
        rec = _users.get(user_id)
        return dict(rec) if rec else None


def get_by_zhihu_uid(zhihu_uid: str) -> dict[str, Any] | None:
    if _pg_enabled():
        return _pg_user_payload(zhihu_uid=zhihu_uid)
    _load()
    with _lock:
        user_id = _zhihu_index.get(str(zhihu_uid))
        return dict(_users[user_id]) if user_id else None


def upsert_zhihu_user(profile: dict[str, Any]) -> dict[str, Any]:
    """按知乎 uid 建档或更新资料。

    profile 来自 https://openapi.zhihu.com/user，关键字段：
      uid / hash_id / fullname / avatar_path / headline

    注意：uid 是 int64，可能超出 JavaScript 安全整数范围，
    这里统一以字符串保存和索引，避免精度丢失。
    """
    if _pg_enabled():
        return _pg_upsert(profile)
    _load()
    zhihu_uid = str(profile.get("uid") or "").strip()
    if not zhihu_uid:
        raise ValueError("zhihu_uid_missing")

    with _lock:
        user_id = _zhihu_index.get(zhihu_uid)
        if user_id:
            rec = _users[user_id]
            # 昵称头像可能变更，每次授权都刷新
            rec["zhihu_hash_id"] = profile.get("hash_id") or rec.get("zhihu_hash_id")
            rec["fullname"] = profile.get("fullname") or rec.get("fullname")
            rec["avatar_url"] = profile.get("avatar_path") or rec.get("avatar_url")
            rec["headline"] = profile.get("headline", rec.get("headline", ""))
            rec["zhihu_connected"] = True
            rec["last_login_at"] = _now_iso()
            _flush()
            return dict(rec)

        rec = {
            "user_id": "user_" + uuid4().hex[:16],
            "zhihu_uid": zhihu_uid,
            "zhihu_hash_id": profile.get("hash_id"),
            "fullname": profile.get("fullname") or "",
            "avatar_url": profile.get("avatar_path") or "",
            "headline": profile.get("headline", ""),
            "zhihu_connected": True,
            # 分身状态由 imports/avatars 流程推进，这里只做初值
            "avatar_id": None,
            "avatar_status": "not_created",
            "created_at": _now_iso(),
            "last_login_at": _now_iso(),
        }
        _users[rec["user_id"]] = rec
        _zhihu_index[zhihu_uid] = rec["user_id"]
        _flush()
        return dict(rec)


def set_zhihu_disconnected(user_id: str) -> None:
    """撤销知乎授权后标记断开，保留用户档案。"""
    _load()
    with _lock:
        rec = _users.get(user_id)
        if rec:
            rec["zhihu_connected"] = False
            _flush()


def count_users() -> int:
    _load()
    with _lock:
        return len(_users)
