"""通知、交友和陌生回答流程的 PostgreSQL + HTTP 可重复验收脚本。

默认使用临时用户和确定性测试 LLM，不调用真实模型接口；生产链路仍通过
``build_llm`` 读取配置。传入 ``--real-llm`` 可切换为真实模型生成行为记忆。
"""
from __future__ import annotations

import argparse
import asyncio
import json
from uuid import uuid4

import httpx

from db.database import connect, initialize_formal
from agent.profile.repository import ProfileRepository
from agent.runtime.llm import LLMResponse
from agent.runtime.notifications import NotificationService


class DeterministicMemoryLLM:
    """返回固定 JSON 的测试模型，验证服务确实消费模型生成的记忆内容。"""

    async def generate(self, prompt: str, **kwargs):
        """根据提示返回稳定的行为记忆 JSON。"""
        return LLMResponse(
            text=json.dumps({"topic": "测试反馈场景", "content": "遇到类似问题时，先确认用户的真实偏好，再决定是否采取行动。"}, ensure_ascii=False),
            model="deterministic-test-model",
        )


def _seed_fixtures() -> dict[str, str]:
    """创建临时用户、分身、对话运行和真实聊天消息。"""
    user_a, user_b = str(uuid4()), str(uuid4())
    repository = ProfileRepository()
    avatar_a = repository.initialize_avatar(user_id=user_a, identity={"display_name": "测试甲", "summary": "通知测试用户甲"}, personality={"scores": {"openness": 5.0}})["avatar_id"]
    avatar_b = repository.initialize_avatar(user_id=user_b, identity={"display_name": "测试乙", "summary": "通知测试用户乙"}, personality={"scores": {"openness": 5.0}})["avatar_id"]
    conversation_id, run_id = str(uuid4()), str(uuid4())
    with connect() as db:
        db.execute("UPDATE users SET external_id=%s WHERE id=%s", (f"test-notification-a-{user_a[:8]}", user_a))
        db.execute("UPDATE users SET external_id=%s WHERE id=%s", (f"test-notification-b-{user_b[:8]}", user_b))
        db.execute("INSERT INTO chat_conversations(id,title) VALUES(%s,%s)", (conversation_id, "通知端到端测试"))
        pa = db.execute("INSERT INTO chat_participants(conversation_id,avatar_id,display_name) VALUES(%s,%s,%s) RETURNING id", (conversation_id, avatar_a, "测试甲 Agent")).fetchone()["id"]
        db.execute("INSERT INTO chat_participants(conversation_id,avatar_id,display_name) VALUES(%s,%s,%s)", (conversation_id, avatar_b, "测试乙 Agent"))
        message_id = db.execute("INSERT INTO chat_messages(conversation_id,participant_id,sequence_no,content) VALUES(%s,%s,1,%s) RETURNING id", (conversation_id, pa, "测试原始聊天消息")).fetchone()["id"]
        db.execute("""INSERT INTO agent_dialogue_runs(id,conversation_id,avatar_a_id,avatar_b_id,user_a_id,user_b_id,status,current_turn,max_rounds)
            VALUES(%s,%s,%s,%s,%s,%s,'completed',1,1)""", (run_id, conversation_id, avatar_a, avatar_b, user_a, user_b))
        evaluation_id = db.execute("""INSERT INTO agent_dialogue_evaluations(dialogue_run_id,evaluator_model,score,great_score,summary)
            VALUES(%s,'test-evaluator',0.95,0.80,'测试高质量对话') RETURNING id""", (run_id,)).fetchone()["id"]
    return {"user_a": user_a, "user_b": user_b, "avatar_a": str(avatar_a), "avatar_b": str(avatar_b), "conversation_id": conversation_id, "run_id": run_id, "message_id": str(message_id), "evaluation_id": str(evaluation_id)}


def _seed_secondary_run(fixtures: dict[str, str]) -> None:
    """为拒绝分支创建同一对用户的第二个匹配批次。"""
    conversation_id, run_id = str(uuid4()), str(uuid4())
    with connect() as db:
        db.execute("INSERT INTO chat_conversations(id,title) VALUES(%s,%s)", (conversation_id, "通知拒绝分支测试"))
        db.execute("INSERT INTO chat_participants(conversation_id,avatar_id,display_name) VALUES(%s,%s,%s),(%s,%s,%s)", (conversation_id, fixtures["avatar_a"], "测试甲 Agent", conversation_id, fixtures["avatar_b"], "测试乙 Agent"))
        db.execute("""INSERT INTO agent_dialogue_runs(id,conversation_id,avatar_a_id,avatar_b_id,user_a_id,user_b_id,status,current_turn,max_rounds)
            VALUES(%s,%s,%s,%s,%s,%s,'completed',1,1)""", (run_id, conversation_id, fixtures["avatar_a"], fixtures["avatar_b"], fixtures["user_a"], fixtures["user_b"]))
    fixtures["secondary_conversation_id"], fixtures["secondary_run_id"] = conversation_id, run_id


def _cleanup_stale_fixtures() -> None:
    """清理上次中断遗留的 test-notification 用户，保证脚本可重复执行。"""
    with connect() as db:
        db.execute("DELETE FROM user_notifications WHERE recipient_user_id IN (SELECT id FROM users WHERE external_id LIKE 'test-notification-%')")
        db.execute("DELETE FROM avatar_friendships WHERE user_a_id IN (SELECT id FROM users WHERE external_id LIKE 'test-notification-%') OR user_b_id IN (SELECT id FROM users WHERE external_id LIKE 'test-notification-%')")
        db.execute("DELETE FROM agent_unknown_responses WHERE user_id IN (SELECT id FROM users WHERE external_id LIKE 'test-notification-%')")
        db.execute("DELETE FROM chat_conversations WHERE id IN (SELECT conversation_id FROM agent_dialogue_runs WHERE user_a_id IN (SELECT id FROM users WHERE external_id LIKE 'test-notification-%') OR user_b_id IN (SELECT id FROM users WHERE external_id LIKE 'test-notification-%'))")
        db.execute("DELETE FROM users WHERE external_id LIKE 'test-notification-%'")


def _cleanup(fixtures: dict[str, str]) -> None:
    """按外键依赖顺序删除本次测试临时数据。"""
    with connect() as db:
        db.execute("DELETE FROM user_notifications WHERE recipient_user_id IN (%s,%s)", (fixtures["user_a"], fixtures["user_b"]))
        db.execute("DELETE FROM avatar_friendships WHERE dialogue_run_id=%s", (fixtures["run_id"],))
        db.execute("DELETE FROM agent_unknown_responses WHERE user_id=%s", (fixtures["user_a"],))
        db.execute("DELETE FROM agent_dialogue_evaluations WHERE dialogue_run_id=%s", (fixtures["run_id"],))
        db.execute("DELETE FROM agent_dialogue_runs WHERE id=%s", (fixtures["run_id"],))
        # 会话删除采用级联，连同参与者和真实消息一起清理，避免头像外键残留。
        db.execute("DELETE FROM chat_conversations WHERE id=%s", (fixtures["conversation_id"],))
        if fixtures.get("secondary_run_id"):
            db.execute("DELETE FROM agent_dialogue_runs WHERE id=%s", (fixtures["secondary_run_id"],))
            db.execute("DELETE FROM chat_conversations WHERE id=%s", (fixtures["secondary_conversation_id"],))
        db.execute("DELETE FROM users WHERE id IN (%s,%s)", (fixtures["user_a"], fixtures["user_b"]))


async def _run_http_checks(fixtures: dict[str, str], *, real_llm: bool) -> dict[str, object]:
    """通过实际 FastAPI ASGI 接口逐项验证通知功能。"""
    from app.main import app
    service = NotificationService()
    friendship_id = service.create_friendship_notifications(dialogue_run_id=fixtures["run_id"], user_a_id=fixtures["user_a"], user_b_id=fixtures["user_b"], avatar_a_id=fixtures["avatar_a"], avatar_b_id=fixtures["avatar_b"], score=0.95, threshold=0.8, summary="测试高质量对话", evaluation_id=fixtures["evaluation_id"])
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        ha = {"X-User-Id": fixtures["user_a"]}
        hb = {"X-User-Id": fixtures["user_b"]}
        heartbeat = await client.get("/v1/twin/notifications/heartbeat", headers=ha)
        assert heartbeat.status_code == 200 and heartbeat.json()["unread_count"] == 1
        unread_count = await client.get("/v1/twin/notifications/unread-count", headers=ha)
        assert unread_count.status_code == 200 and unread_count.json()["has_unread"] is True
        listed = await client.get("/v1/twin/notifications", headers=ha)
        assert listed.status_code == 200 and listed.json()["total"] == 1
        invitation_a = listed.json()["items"][0]["id"]
        detail = await client.get(f"/v1/twin/notifications/{invitation_a}", headers=ha)
        assert detail.status_code == 200 and detail.json()["status"] == "read"
        decision_a = await client.post(f"/v1/twin/notifications/{invitation_a}/decision", headers=ha, json={"decision": "accepted"})
        assert decision_a.status_code == 200 and decision_a.json()["status"] == "pending"
        listed_b = await client.get("/v1/twin/notifications", headers=hb)
        invitation_b = listed_b.json()["items"][0]["id"]
        decision_b = await client.post(f"/v1/twin/notifications/{invitation_b}/decision", headers=hb, json={"decision": "accepted"})
        assert decision_b.status_code == 200 and decision_b.json()["status"] == "accepted"
        connected = await client.get("/v1/twin/notifications", headers=ha, params={"notification_type": "friendship_connected"})
        assert connected.status_code == 200 and connected.json()["total"] == 1 and connected.json()["items"][0]["payload"]["external_id"].startswith("test-notification-")
        unauthorized = await client.get(f"/v1/twin/notifications/{invitation_a}", headers={"X-User-Id": str(uuid4())})
        assert unauthorized.status_code == 404

        # 验证另一条匹配被单方拒绝时，不会生成 connected 通知。
        _seed_secondary_run(fixtures)
        rejected_friendship = service.create_friendship_notifications(dialogue_run_id=fixtures["secondary_run_id"], user_a_id=fixtures["user_a"], user_b_id=fixtures["user_b"], avatar_a_id=fixtures["avatar_a"], avatar_b_id=fixtures["avatar_b"], score=0.91, threshold=0.8, summary="测试拒绝分支")
        rejected_list = await client.get("/v1/twin/notifications", headers=hb, params={"notification_type": "friendship_invitation"})
        rejected_notification = next(item["id"] for item in rejected_list.json()["items"] if item["friendship_id"] == rejected_friendship)
        rejected = await client.post(f"/v1/twin/notifications/{rejected_notification}/decision", headers=hb, json={"decision": "rejected"})
        assert rejected.status_code == 200 and rejected.json()["status"] == "rejected_by_b"
        rejected_connected = await client.get("/v1/twin/notifications", headers=ha, params={"notification_type": "friendship_connected"})
        assert rejected_connected.status_code == 200 and rejected_connected.json()["total"] == 1

        unknown_id = service.create_unknown_response(user_id=fixtures["user_a"], avatar_id=fixtures["avatar_a"], question="测试陌生问题", answer="测试 Agent 回答", retrieval_meta={"unknown_threshold": 0.5, "top_memory_score": 0.1}, dialogue_run_id=fixtures["run_id"], conversation_id=fixtures["conversation_id"], chat_message_id=fixtures["message_id"])
        unknown_list = await client.get("/v1/twin/notifications", headers=ha, params={"notification_type": "unknown_agent_response"})
        unknown_notification = unknown_list.json()["items"][0]["id"]
        await client.get(f"/v1/twin/notifications/{unknown_notification}", headers=ha)

        import agent.runtime.model_builder as model_builder
        original_builder = model_builder.build_llm
        if not real_llm:
            model_builder.build_llm = lambda: DeterministicMemoryLLM()
        try:
            feedback = await client.post(f"/v1/twin/notifications/{unknown_notification}/decision", headers=ha, json={"feedback": "unexpected"})
        finally:
            model_builder.build_llm = original_builder
        assert feedback.status_code == 200 and feedback.json()["status"] == "applied"
        with connect() as db:
            memory = db.execute("SELECT content,status,topic FROM avatar_memories WHERE avatar_id=%s AND structured_data->>'source'='unknown_agent_response' ORDER BY created_at DESC LIMIT 1", (fixtures["avatar_a"],)).fetchone()
        assert memory and memory["status"] == "unconfirmed"
        expected_unknown = service.create_unknown_response(user_id=fixtures["user_a"], avatar_id=fixtures["avatar_a"], question="测试符合预期问题", answer="测试符合预期回答", retrieval_meta={"unknown_threshold": 0.5, "top_memory_score": 0.1}, dialogue_run_id=fixtures["run_id"], conversation_id=fixtures["conversation_id"], chat_message_id=fixtures["message_id"])
        expected_list = await client.get("/v1/twin/notifications", headers=ha, params={"notification_type": "unknown_agent_response"})
        expected_notification = next(item["id"] for item in expected_list.json()["items"] if item["unknown_response_id"] == expected_unknown)
        expected = await client.post(f"/v1/twin/notifications/{expected_notification}/decision", headers=ha, json={"feedback": "expected"})
        assert expected.status_code == 200 and expected.json()["status"] == "accepted"
        return {"friendship_id": friendship_id, "invitation_acceptance": "双方均已同意", "connected_notifications": connected.json()["total"], "rejected_friendship": rejected_friendship, "rejected_status": rejected.json()["status"], "unknown_response_id": unknown_id, "memory_status": memory["status"], "memory_topic": memory["topic"], "memory_content": memory["content"], "expected_feedback_status": expected.json()["status"], "llm_mode": "real" if real_llm else "deterministic-test"}


def main() -> None:
    """初始化正式表结构、运行 HTTP 验收并清理临时数据。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--real-llm", action="store_true", help="使用当前配置的真实 LLM 生成行为记忆")
    args = parser.parse_args()
    initialize_formal()
    _cleanup_stale_fixtures()
    fixtures = _seed_fixtures()
    try:
        result = asyncio.run(_run_http_checks(fixtures, real_llm=args.real_llm))
        print(json.dumps({"ok": True, "fixtures": fixtures, "result": result}, ensure_ascii=False, indent=2, default=str))
    finally:
        _cleanup(fixtures)


if __name__ == "__main__":
    main()
