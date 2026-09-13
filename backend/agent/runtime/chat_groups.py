"""Agent 聊天组查询服务。"""
from __future__ import annotations

from typing import Any

from db.database import connect


class ChatGroupService:
    """查询当前用户参与的聊天组，不重复保存聊天正文。"""

    def count_my_chat_groups(self, user_id: str, *, status: str | None = None) -> int:
        """统计用户作为发起方或被邀请方参与的聊天组数量。"""
        where = "(initiator_user_id=%s OR invited_user_id=%s)"
        params: list[Any] = [user_id, user_id]
        if status:
            where += " AND status=%s"
            params.append(status)
        with connect() as db:
            return int(db.execute(f"SELECT count(*) AS n FROM agent_chat_groups WHERE {where}", params).fetchone()["n"])

    def list_my_chat_groups(self, user_id: str, *, page: int = 1, page_size: int = 20, status: str | None = None) -> dict[str, object]:
        """分页返回聊天组双方、状态、时间和消息数量。"""
        if page < 1 or page_size < 1 or page_size > 100:
            raise ValueError("分页参数无效")
        where = "(g.initiator_user_id=%s OR g.invited_user_id=%s)"
        params: list[Any] = [user_id, user_id]
        if status:
            where += " AND g.status=%s"
            params.append(status)
        total = self.count_my_chat_groups(user_id, status=status)
        params.extend([page_size, (page - 1) * page_size])
        with connect() as db:
            rows = db.execute(f"""SELECT g.*, ia.display_name AS initiator_name, ba.display_name AS invited_name
                FROM agent_chat_groups g
                JOIN user_avatars ia ON ia.id=g.initiator_avatar_id
                JOIN user_avatars ba ON ba.id=g.invited_avatar_id
                WHERE {where} ORDER BY g.started_at DESC LIMIT %s OFFSET %s""", params).fetchall()
        items = []
        for row in rows:
            items.append({"chat_no": row["chat_no"], "dialogue_run_id": str(row["dialogue_run_id"]), "conversation_id": str(row["conversation_id"]), "initiator": {"user_id": str(row["initiator_user_id"]), "avatar_id": str(row["initiator_avatar_id"]), "display_name": row["initiator_name"]}, "invited": {"user_id": str(row["invited_user_id"]), "avatar_id": str(row["invited_avatar_id"]), "display_name": row["invited_name"]}, "status": row["status"], "started_at": row["started_at"].isoformat(), "ended_at": row["ended_at"].isoformat() if row["ended_at"] else None, "message_count": row["message_count"]})
        return {"items": items, "page": page, "page_size": page_size, "total": total}

    def get_chat_group_messages(self, user_id: str, chat_no: str) -> dict[str, object] | None:
        """校验用户归属后返回聊天组和按序排列的完整消息。"""
        with connect() as db:
            group = db.execute("""SELECT g.*, ia.display_name AS initiator_name, ba.display_name AS invited_name
                FROM agent_chat_groups g JOIN user_avatars ia ON ia.id=g.initiator_avatar_id JOIN user_avatars ba ON ba.id=g.invited_avatar_id
                WHERE g.chat_no=%s AND (g.initiator_user_id=%s OR g.invited_user_id=%s)""", (chat_no, user_id, user_id)).fetchone()
            if not group:
                return None
            rows = db.execute("""SELECT m.id,m.sequence_no,m.content,m.message_type,m.sent_at,m.metadata,p.avatar_id,p.display_name
                FROM chat_messages m JOIN chat_participants p ON p.id=m.participant_id
                WHERE m.conversation_id=%s AND m.deleted_at IS NULL ORDER BY m.sequence_no ASC""", (group["conversation_id"],)).fetchall()
        return {"chat_no": group["chat_no"], "dialogue_run_id": str(group["dialogue_run_id"]), "conversation_id": str(group["conversation_id"]), "initiator": {"user_id": str(group["initiator_user_id"]), "avatar_id": str(group["initiator_avatar_id"]), "display_name": group["initiator_name"]}, "invited": {"user_id": str(group["invited_user_id"]), "avatar_id": str(group["invited_avatar_id"]), "display_name": group["invited_name"]}, "status": group["status"], "started_at": group["started_at"].isoformat(), "ended_at": group["ended_at"].isoformat() if group["ended_at"] else None, "messages": [{"message_id": str(r["id"]), "sequence_no": r["sequence_no"], "sender_avatar_id": str(r["avatar_id"]), "sender_name": r["display_name"], "content": r["content"], "message_type": r["message_type"], "sent_at": r["sent_at"].isoformat(), "metadata": r["metadata"] or {}} for r in rows]}

