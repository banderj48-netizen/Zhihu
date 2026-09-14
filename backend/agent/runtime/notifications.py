"""通知、交友关系和陌生回答的事务服务。"""
from __future__ import annotations

import json
import re
from typing import Any
from psycopg.types.json import Jsonb

from db.database import connect
from agent.profile.langgraph_tools import create_behavior_memory_tool


class NotificationService:
    """封装通知盒子、交友确认和陌生回答反馈，路由不直接操作数据库。"""

    def unread_count(self, user_id: str) -> dict[str, Any]:
        """返回当前用户未读数量和红点状态。"""
        with connect() as db:
            row = db.execute("SELECT count(*) AS count, max(created_at) AS latest_at FROM user_notifications WHERE recipient_user_id=%s AND status='unread'", (user_id,)).fetchone()
        count = int(row["count"] or 0)
        return {"unread_count": count, "has_unread": count > 0, "latest_at": row["latest_at"]}

    def list_notifications(self, user_id: str, *, page: int = 1, page_size: int = 20, status: str | None = None, notification_type: str | None = None) -> dict[str, Any]:
        """分页读取当前用户通知，并限制分页参数避免过大查询。"""
        page = max(1, page)
        page_size = max(1, min(page_size, 100))
        conditions = ["recipient_user_id=%s"]
        params: list[Any] = [user_id]
        if status:
            conditions.append("status=%s")
            params.append(status)
        if notification_type:
            conditions.append("notification_type=%s")
            params.append(notification_type)
        where = " AND ".join(conditions)
        with connect() as db:
            rows = db.execute(f"SELECT * FROM user_notifications WHERE {where} ORDER BY created_at DESC LIMIT %s OFFSET %s", (*params, page_size, (page - 1) * page_size)).fetchall()
            total = db.execute(f"SELECT count(*) AS count FROM user_notifications WHERE {where}", tuple(params)).fetchone()["count"]
        return {"items": [dict(row) for row in rows], "page": page, "page_size": page_size, "total": int(total)}

    def get_notification(self, user_id: str, notification_id: str) -> dict[str, Any] | None:
        """读取通知详情，并将未读消息原子地标记为已读。"""
        with connect() as db:
            row = db.execute("UPDATE user_notifications SET status='read', read_at=COALESCE(read_at,now()) WHERE id=%s AND recipient_user_id=%s AND status='unread' RETURNING *", (notification_id, user_id)).fetchone()
            if not row:
                row = db.execute("SELECT * FROM user_notifications WHERE id=%s AND recipient_user_id=%s", (notification_id, user_id)).fetchone()
        return dict(row) if row else None

    def create_friendship_notifications(self, *, dialogue_run_id: str, user_a_id: str, user_b_id: str, avatar_a_id: str, avatar_b_id: str, score: float, threshold: float, summary: str | None, evaluation_id: str | None = None) -> str:
        """幂等创建交友关系及双方邀请通知。"""
        friendship_id = self.create_friendship_record(dialogue_run_id=dialogue_run_id, user_a_id=user_a_id, user_b_id=user_b_id, avatar_a_id=avatar_a_id, avatar_b_id=avatar_b_id, score=score, threshold=threshold, summary=summary, evaluation_id=evaluation_id)
        self.send_friendship_invitation(friendship_id, dialogue_run_id, user_a_id, user_b_id, avatar_b_id, score, threshold)
        self.send_friendship_invitation(friendship_id, dialogue_run_id, user_b_id, user_a_id, avatar_a_id, score, threshold)
        return friendship_id

    def create_friendship_record(self, *, dialogue_run_id: str, user_a_id: str, user_b_id: str, avatar_a_id: str, avatar_b_id: str, score: float, threshold: float, summary: str | None, evaluation_id: str | None = None) -> str:
        """只创建交友关系记录，不发送通知，供分阶段推送场景使用。"""
        with connect() as db:
            row = db.execute("""INSERT INTO avatar_friendships(dialogue_run_id,user_a_id,user_b_id,avatar_a_id,avatar_b_id,evaluation_id,score,threshold,match_summary)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(dialogue_run_id) DO UPDATE SET score=EXCLUDED.score,threshold=EXCLUDED.threshold,match_summary=EXCLUDED.match_summary RETURNING id""", (dialogue_run_id, user_a_id, user_b_id, avatar_a_id, avatar_b_id, evaluation_id, score, threshold, summary)).fetchone()
            return str(row["id"])

    def send_friendship_invitation(self, friendship_id: str, dialogue_run_id: str, recipient_user_id: str, other_user_id: str, other_avatar_id: str, score: float, threshold: float) -> None:
        """向指定用户发送一条幂等交友邀请，正文不泄露对方知乎身份。"""
        title = "你的分身遇到了聊得很投机的对象"
        body = "您的分身和另一位分身聊得很开心，评判结果显示你们可能适合成为朋友，是否同意？"
        payload = {"friendship_id": friendship_id, "score": score, "threshold": threshold, "other_user_id": other_user_id, "other_avatar_id": other_avatar_id}
        with connect() as db:
            db.execute("""INSERT INTO user_notifications(recipient_user_id,notification_type,title,body,payload,source_dialogue_run_id,friendship_id)
                VALUES(%s,'friendship_invitation',%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""", (recipient_user_id, title, body, Jsonb(payload), dialogue_run_id, friendship_id))

    def decide_friendship(self, user_id: str, notification_id: str, decision: str) -> dict[str, Any]:
        """保存单方交友决定；双方同意时事务内生成双方成功通知。"""
        if decision not in {"accepted", "rejected"}:
            raise ValueError("decision 必须是 accepted 或 rejected")
        with connect() as db:
            note = db.execute("SELECT * FROM user_notifications WHERE id=%s AND recipient_user_id=%s FOR UPDATE", (notification_id, user_id)).fetchone()
            if not note or note["notification_type"] != "friendship_invitation" or not note["friendship_id"]:
                raise ValueError("交友通知不存在")
            friendship = db.execute("SELECT * FROM avatar_friendships WHERE id=%s FOR UPDATE", (note["friendship_id"],)).fetchone()
            if not friendship:
                raise ValueError("交友关系不存在")
            side = "a" if str(friendship["user_a_id"]) == str(user_id) else "b" if str(friendship["user_b_id"]) == str(user_id) else None
            if not side:
                raise ValueError("无权处理该通知")
            # 用户决定是终态，重复提交直接返回当前关系，避免已拒绝后被改写。
            current_decision = friendship[f"user_{side}_decision"]
            if current_decision != "pending":
                return {"notification_id": str(notification_id), "decision": current_decision, "friendship_id": str(friendship["id"]), "status": friendship["status"]}
            other_side = "b" if side == "a" else "a"
            db.execute(f"""UPDATE avatar_friendships SET
                user_{side}_decision=%s,
                user_{side}_decided_at=COALESCE(user_{side}_decided_at,now()),
                status=CASE WHEN %s='rejected' THEN 'rejected_by_{side}'
                    WHEN %s='accepted' AND user_{other_side}_decision='accepted' THEN 'accepted'
                    ELSE 'pending' END,
                updated_at=now(),
                connected_at=CASE WHEN %s='accepted' AND user_{other_side}_decision='accepted' THEN COALESCE(connected_at,now()) ELSE connected_at END
                WHERE id=%s""", (decision, decision, decision, decision, note["friendship_id"]))
            db.execute("UPDATE user_notifications SET status=%s,action_at=now(),read_at=COALESCE(read_at,now()) WHERE id=%s AND recipient_user_id=%s", (decision, notification_id, user_id))
            current = db.execute("SELECT * FROM avatar_friendships WHERE id=%s", (note["friendship_id"],)).fetchone()
            if current["status"] == "accepted":
                for recipient, other_user, other_avatar in ((current["user_a_id"], current["user_b_id"], current["avatar_b_id"]), (current["user_b_id"], current["user_a_id"], current["avatar_a_id"])):
                    detail = db.execute("SELECT u.external_id, a.display_name, a.metadata FROM users u JOIN user_avatars a ON a.id=%s WHERE u.id=%s", (other_avatar, other_user)).fetchone()
                    payload = {"friendship_id": str(current["id"]), "user_id": str(other_user), "avatar_id": str(other_avatar), "external_id": detail["external_id"] if detail else None, "display_name": detail["display_name"] if detail else None}
                    db.execute("""INSERT INTO user_notifications(recipient_user_id,notification_type,title,body,payload,friendship_id)
                        VALUES(%s,'friendship_connected','你们已互相同意成为朋友','双方都同意了交友请求，现在可以查看对方的知乎信息。',%s,%s) ON CONFLICT DO NOTHING""", (recipient, Jsonb(payload), current["id"]))
            return {"notification_id": str(notification_id), "decision": decision, "friendship_id": str(current["id"]), "status": current["status"]}

    def create_unknown_response(self, *, user_id: str, avatar_id: str, question: str, answer: str, retrieval_meta: dict[str, Any], dialogue_run_id: str | None = None, conversation_id: str | None = None, chat_message_id: str | None = None) -> str:
        """记录一次低相关度回答，并创建幂等用户反馈通知。"""
        threshold = float(retrieval_meta.get("unknown_threshold", 0.5))
        top_score = retrieval_meta.get("top_memory_score")
        with connect() as db:
            row = db.execute("""INSERT INTO agent_unknown_responses(user_id,avatar_id,dialogue_run_id,conversation_id,chat_message_id,question,agent_answer,retrieval_threshold,top_relevance_score,retrieval_meta)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""", (user_id, avatar_id, dialogue_run_id, conversation_id, chat_message_id, question, answer, threshold, top_score, Jsonb(retrieval_meta))).fetchone()
            unknown_id = str(row["id"])
            db.execute("""INSERT INTO user_notifications(recipient_user_id,notification_type,title,body,payload,source_dialogue_run_id,source_chat_message_id,unknown_response_id)
                VALUES(%s,'unknown_agent_response','请确认你的分身这次回答是否符合预期',%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""", (user_id, f"你的分身面对“{question}”回答了：“{answer}”，你觉得符合预期吗？", Jsonb({"unknown_response_id": unknown_id, "question": question, "agent_answer": answer}), dialogue_run_id, chat_message_id, unknown_id))
        return unknown_id

    def attach_unknown_message(self, unknown_id: str, chat_message_id: str) -> None:
        """把已落库的真实聊天消息 ID 回填到陌生回答事实和通知。"""
        with connect() as db:
            db.execute("UPDATE agent_unknown_responses SET chat_message_id=%s WHERE id=%s", (chat_message_id, unknown_id))
            db.execute("UPDATE user_notifications SET source_chat_message_id=%s WHERE unknown_response_id=%s", (chat_message_id, unknown_id))

    def decide_unknown_response(self, user_id: str, notification_id: str, feedback: str, feedback_text: str | None = None) -> dict[str, Any]:
        """保存陌生回答反馈；不符合预期时保留 rejected 状态供记忆提案流程消费。"""
        if feedback not in {"expected", "unexpected"}:
            raise ValueError("feedback 必须是 expected 或 unexpected")
        proposal_result: dict[str, Any] | None = None
        with connect() as db:
            note = db.execute("SELECT * FROM user_notifications WHERE id=%s AND recipient_user_id=%s FOR UPDATE", (notification_id, user_id)).fetchone()
            if not note or not note["unknown_response_id"]:
                raise ValueError("陌生回答通知不存在")
            existing = db.execute("SELECT feedback_status,user_feedback FROM agent_unknown_responses WHERE id=%s AND user_id=%s", (note["unknown_response_id"], user_id)).fetchone()
            if not existing:
                raise ValueError("陌生回答事实不存在")
            if existing["feedback_status"] != "pending":
                return {"notification_id": str(notification_id), "feedback": existing["user_feedback"], "status": existing["feedback_status"]}
            state = "accepted" if feedback == "expected" else "rejected"
            db.execute("UPDATE agent_unknown_responses SET user_feedback=%s,feedback_text=%s,feedback_status=%s,feedback_at=now() WHERE id=%s AND user_id=%s", (feedback, feedback_text, state, note["unknown_response_id"], user_id))
            db.execute("UPDATE user_notifications SET status=%s,action_at=now(),read_at=COALESCE(read_at,now()) WHERE id=%s", (state, notification_id))
            unknown = db.execute("SELECT avatar_id,question,agent_answer FROM agent_unknown_responses WHERE id=%s", (note["unknown_response_id"],)).fetchone()
        if feedback == "unexpected" and feedback_text and unknown:
            # 调用方已经完成模型判断时，使用模型生成的修正内容进入既有提案函数。
            try:
                behavior_tool = create_behavior_memory_tool(user_id, str(unknown["avatar_id"]), None)
                proposal_result = behavior_tool.invoke({
                    "topic": "用户反馈纠正",
                    "content": feedback_text.strip(),
                    "structured_data": {"question": unknown["question"], "agent_answer": unknown["agent_answer"], "source": "unknown_agent_response"},
                    "confidence": 0.9,
                })
                with connect() as db:
                    db.execute("UPDATE agent_unknown_responses SET feedback_status='applied' WHERE id=%s", (note["unknown_response_id"],))
            except Exception:
                with connect() as db:
                    db.execute("UPDATE agent_unknown_responses SET feedback_status='failed' WHERE id=%s", (note["unknown_response_id"],))
        return {"notification_id": str(notification_id), "feedback": feedback, "status": "applied" if proposal_result else state, "proposal": proposal_result}

    async def decide_unknown_response_with_model(self, user_id: str, notification_id: str, feedback: str, feedback_text: str | None = None) -> dict[str, Any]:
        """先让大模型判断行为修正内容，再调用行为记忆函数落库。"""
        if feedback != "unexpected":
            return self.decide_unknown_response(user_id, notification_id, feedback, feedback_text)
        with connect() as db:
            row = db.execute("""SELECT u.question,u.agent_answer,u.avatar_id
                FROM user_notifications n JOIN agent_unknown_responses u ON u.id=n.unknown_response_id
                WHERE n.id=%s AND n.recipient_user_id=%s FOR UPDATE""", (notification_id, user_id)).fetchone()
        if not row:
            raise ValueError("陌生回答通知不存在")
        memory = await self._judge_behavior_memory(row["question"], row["agent_answer"], feedback_text)
        return self._apply_unknown_feedback(user_id, notification_id, feedback, feedback_text, memory)

    async def _judge_behavior_memory(self, question: str, answer: str, feedback_text: str | None) -> dict[str, str]:
        """使用注入式 LLM 生成行为记忆主题和内容，失败时安全回退。"""
        prompt = json.dumps({"question": question, "agent_answer": answer, "user_feedback": feedback_text or "用户认为该回答不符合预期", "要求": "生成一条简洁、可执行、隐私安全的行为记忆，描述以后遇到类似情境应如何选择。只返回 JSON：topic、content。"}, ensure_ascii=False)
        try:
            from agent.runtime.model_builder import build_llm
            llm = build_llm()
            response = await llm.generate(prompt, system_prompt="你负责把用户对数字分身回答的否定反馈转换成未确认行为记忆。不得编造用户身份，不得推断敏感属性。", temperature=0, max_tokens=300)
            raw = response.text.strip()
            match = re.search(r"\{.*\}", raw, re.S)
            data = json.loads(match.group(0) if match else raw)
            topic, content = str(data.get("topic") or "用户反馈纠正"), str(data.get("content") or "")
            if content.strip():
                return {"topic": topic[:200], "content": content.strip()[:2000], "source": "llm"}
        except Exception:
            pass
        # 没有可用模型时仍保留确定性、未确认的安全提案，保证流程可回归。
        fallback = feedback_text.strip() if feedback_text and feedback_text.strip() else f"面对“{question}”这类情况，不要重复本次回答中的选择；先向用户确认偏好再行动。"
        return {"topic": "用户反馈纠正", "content": fallback[:2000], "source": "fallback"}

    def _apply_unknown_feedback(self, user_id: str, notification_id: str, feedback: str, feedback_text: str | None, memory: dict[str, str]) -> dict[str, Any]:
        """把模型生成的行为记忆提交给现有画像提案函数并更新反馈状态。"""
        if feedback != "unexpected":
            return self.decide_unknown_response(user_id, notification_id, feedback, feedback_text)
        with connect() as db:
            note = db.execute("SELECT * FROM user_notifications WHERE id=%s AND recipient_user_id=%s FOR UPDATE", (notification_id, user_id)).fetchone()
            if not note or not note["unknown_response_id"]:
                raise ValueError("陌生回答通知不存在")
            existing = db.execute("SELECT feedback_status, user_feedback, avatar_id, question, agent_answer FROM agent_unknown_responses WHERE id=%s AND user_id=%s", (note["unknown_response_id"], user_id)).fetchone()
            if not existing:
                raise ValueError("陌生回答事实不存在")
            if existing["feedback_status"] != "pending":
                return {"notification_id": str(notification_id), "feedback": existing["user_feedback"], "status": existing["feedback_status"]}
            db.execute("UPDATE agent_unknown_responses SET user_feedback='unexpected',feedback_text=%s,feedback_status='rejected',feedback_at=now() WHERE id=%s", (feedback_text, note["unknown_response_id"]))
            db.execute("UPDATE user_notifications SET status='rejected',action_at=now(),read_at=COALESCE(read_at,now()) WHERE id=%s", (notification_id,))
        try:
            behavior_tool = create_behavior_memory_tool(user_id, str(existing["avatar_id"]), None)
            proposal = behavior_tool.invoke({"topic": memory["topic"], "content": memory["content"], "structured_data": {"question": existing["question"], "agent_answer": existing["agent_answer"], "generator": memory.get("source", "llm"), "source": "unknown_agent_response"}, "confidence": 0.9})
            with connect() as db:
                db.execute("UPDATE agent_unknown_responses SET feedback_status='applied' WHERE id=%s", (note["unknown_response_id"],))
            return {"notification_id": str(notification_id), "feedback": feedback, "status": "applied", "proposal": proposal, "memory_generation": memory.get("source")}
        except Exception as exc:
            with connect() as db:
                db.execute("UPDATE agent_unknown_responses SET feedback_status='failed',metadata=metadata || %s WHERE id=%s", (Jsonb({"memory_error": str(exc)}), note["unknown_response_id"]))
            return {"notification_id": str(notification_id), "feedback": feedback, "status": "failed", "error": str(exc), "memory_generation": memory.get("source")}
