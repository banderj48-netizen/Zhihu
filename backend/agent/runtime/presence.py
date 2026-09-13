"""看山场景、候选和占用状态服务。

所有匹配都把当前登录用户的 avatar 作为 A，只从场景空闲池选择 B。
"""
from __future__ import annotations

import random
from typing import Any

from db.database import connect
from psycopg.types.json import Jsonb


DEFAULT_SCENES = [
    {"id": "cafe", "name": "咖啡馆"},
    {"id": "library", "name": "图书馆"},
    {"id": "bar", "name": "小酒馆"},
    {"id": "theater", "name": "戏剧院"},
    {"id": "lecture", "name": "讲座"},
]


class PresenceService:
    """读取场景候选并以条件更新方式占用/释放数字分身。"""

    def list_scenes(self) -> list[dict[str, Any]]:
        """返回稳定的场景目录；前端可直接用 id 进入场景。"""
        return list(DEFAULT_SCENES)

    def list_candidates(self, scene_id: str, *, exclude_avatar_id: str | None = None) -> list[dict[str, Any]]:
        """查询指定场景中的空闲 Agent，并过滤当前用户自己的 Agent。"""
        try:
            with connect() as db:
                rows = db.execute(
                    """SELECT p.avatar_id, p.scene_id, p.status, p.display_summary,
                              COALESCE(a.display_name, '看山') AS display_name
                       FROM agent_scene_presence p
                       LEFT JOIN user_avatars a ON a.id=p.avatar_id
                      WHERE p.scene_id=%s AND p.status='idle'""",
                    (scene_id,),
                ).fetchall()
            return [dict(row) for row in rows if not exclude_avatar_id or str(row["avatar_id"]) != str(exclude_avatar_id)]
        except Exception:
            # 数据库尚未执行在场脚本时，返回空列表而不是污染前端 Mock 数据。
            return []

    def ensure_presence(self, avatar_id: str, scene_id: str, summary: dict[str, Any] | None = None) -> None:
        """首次进入场景时创建空闲记录，重复进入不会覆盖 busy 状态。"""
        with connect() as db:
            db.execute("""INSERT INTO agent_scene_presence(avatar_id,scene_id,status,display_summary)
                VALUES(%s,%s,'idle',%s) ON CONFLICT(avatar_id,scene_id) DO NOTHING""", (avatar_id, scene_id, Jsonb(summary or {})))

    def occupy(self, avatar_id: str, scene_id: str, run_id: str) -> bool:
        """原子地把一个空闲 Agent 标为 busy，防止并发重复匹配。"""
        with connect() as db:
            if run_id:
                row = db.execute("""UPDATE agent_scene_presence SET status='busy', current_dialogue_run_id=%s, updated_at=now()
                    WHERE avatar_id=%s AND scene_id=%s AND status='idle' RETURNING avatar_id""", (run_id, avatar_id, scene_id)).fetchone()
            else:
                row = db.execute("""UPDATE agent_scene_presence SET status='busy', current_dialogue_run_id=NULL, updated_at=now()
                    WHERE avatar_id=%s AND scene_id=%s AND status='idle' RETURNING avatar_id""", (avatar_id, scene_id)).fetchone()
            return bool(row)

    def release(self, avatar_id: str, scene_id: str, run_id: str | None = None) -> None:
        """释放当前运行占用的 Agent；带 run_id 防止误释放新会话。"""
        with connect() as db:
            if run_id:
                db.execute(
                    """UPDATE agent_scene_presence SET status='idle', current_dialogue_run_id=NULL, updated_at=now()
                         WHERE avatar_id=%s AND scene_id=%s AND current_dialogue_run_id=%s""",
                    (avatar_id, scene_id, run_id),
                )
            else:
                db.execute(
                    """UPDATE agent_scene_presence SET status='idle', current_dialogue_run_id=NULL, updated_at=now()
                         WHERE avatar_id=%s AND scene_id=%s""",
                    (avatar_id, scene_id),
                )

    def choose_random(self, candidates: list[dict[str, Any]]) -> dict[str, Any]:
        """从候选池随机返回一个候选。"""
        if not candidates:
            raise ValueError("当前场景暂无空闲看山")
        return random.choice(candidates)
