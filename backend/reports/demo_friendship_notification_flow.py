"""按真实顺序演示 A、B 双方交友通知流程，并打印每一步数据库快照。

脚本只创建 external_id 以 ``demo-friendship-`` 开头的临时用户，默认结束后清理。
如需在 pgAdmin 中继续检查最终数据，可增加 ``--keep`` 保留测试数据。
"""
from __future__ import annotations

import argparse
import json
from uuid import uuid4

from agent.profile.repository import ProfileRepository
from agent.runtime.notifications import NotificationService
from db.database import connect, initialize_formal


def _seed() -> dict[str, str]:
    """创建本次演示使用的两个临时用户、分身和对话批次。"""
    user_a, user_b = str(uuid4()), str(uuid4())
    repository = ProfileRepository()
    avatar_a = repository.initialize_avatar(user_id=user_a, identity={"display_name": "演示用户A", "summary": "交友流程演示 A"}, personality={"scores": {"openness": 5.0}})["avatar_id"]
    avatar_b = repository.initialize_avatar(user_id=user_b, identity={"display_name": "演示用户B", "summary": "交友流程演示 B"}, personality={"scores": {"openness": 5.0}})["avatar_id"]
    conversation_id, run_id = str(uuid4()), str(uuid4())
    with connect() as db:
        db.execute("UPDATE users SET external_id=%s WHERE id=%s", (f"demo-friendship-a-{user_a[:8]}", user_a))
        db.execute("UPDATE users SET external_id=%s WHERE id=%s", (f"demo-friendship-b-{user_b[:8]}", user_b))
        db.execute("INSERT INTO chat_conversations(id,title) VALUES(%s,%s)", (conversation_id, "交友通知顺序演示"))
        db.execute("""INSERT INTO agent_dialogue_runs(id,conversation_id,avatar_a_id,avatar_b_id,user_a_id,user_b_id,status,current_turn,max_rounds)
            VALUES(%s,%s,%s,%s,%s,%s,'completed',10,10)""", (run_id, conversation_id, avatar_a, avatar_b, user_a, user_b))
    return {"user_a": user_a, "user_b": user_b, "avatar_a": str(avatar_a), "avatar_b": str(avatar_b), "conversation_id": conversation_id, "run_id": run_id}


def _snapshot(label: str, fixtures: dict[str, str]) -> None:
    """打印交友关系和通知表的当前真实内容。"""
    with connect() as db:
        friendship = db.execute("""SELECT id,dialogue_run_id,user_a_id,user_b_id,user_a_decision,user_b_decision,status,score,threshold,created_at,updated_at,connected_at
            FROM avatar_friendships WHERE dialogue_run_id=%s""", (fixtures["run_id"],)).fetchall()
        notifications = db.execute("""SELECT id,recipient_user_id,notification_type,title,status,read_at,action_at,friendship_id,payload,created_at
            FROM user_notifications WHERE friendship_id IN (SELECT id FROM avatar_friendships WHERE dialogue_run_id=%s)
            ORDER BY created_at ASC""", (fixtures["run_id"],)).fetchall()
    print(f"\n===== {label} =====")
    print("avatar_friendships:")
    print(json.dumps([dict(row) for row in friendship], ensure_ascii=False, indent=2, default=str))
    print("user_notifications:")
    print(json.dumps([dict(row) for row in notifications], ensure_ascii=False, indent=2, default=str))


def _cleanup(fixtures: dict[str, str]) -> None:
    """按外键依赖顺序清理临时演示数据。"""
    with connect() as db:
        db.execute("DELETE FROM user_notifications WHERE recipient_user_id IN (%s,%s)", (fixtures["user_a"], fixtures["user_b"]))
        db.execute("DELETE FROM avatar_friendships WHERE dialogue_run_id=%s", (fixtures["run_id"],))
        db.execute("DELETE FROM chat_conversations WHERE id=%s", (fixtures["conversation_id"],))
        db.execute("DELETE FROM users WHERE id IN (%s,%s)", (fixtures["user_a"], fixtures["user_b"]))


def main() -> None:
    """执行 A 推送、A 同意、B 推送、B 同意四个可审计步骤。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep", action="store_true", help="演示结束后保留临时数据库记录")
    args = parser.parse_args()
    initialize_formal()
    fixtures = _seed()
    service = NotificationService()
    try:
        friendship_id = service.create_friendship_record(dialogue_run_id=fixtures["run_id"], user_a_id=fixtures["user_a"], user_b_id=fixtures["user_b"], avatar_a_id=fixtures["avatar_a"], avatar_b_id=fixtures["avatar_b"], score=0.96, threshold=0.8, summary="两位 Agent 在全部轮次中表现出较高契合度")
        service.send_friendship_invitation(friendship_id, fixtures["run_id"], fixtures["user_a"], fixtures["user_b"], fixtures["avatar_b"], 0.96, 0.8)
        _snapshot("步骤1：系统只向 A 推送交友邀请", fixtures)

        with connect() as db:
            invitation_a = db.execute("SELECT id FROM user_notifications WHERE recipient_user_id=%s AND friendship_id=%s AND notification_type='friendship_invitation'", (fixtures["user_a"], friendship_id)).fetchone()["id"]
        service.get_notification(fixtures["user_a"], str(invitation_a))
        service.decide_friendship(fixtures["user_a"], str(invitation_a), "accepted")
        _snapshot("步骤2：A 查看并同意，B 此时还没有通知", fixtures)

        service.send_friendship_invitation(friendship_id, fixtures["run_id"], fixtures["user_b"], fixtures["user_a"], fixtures["avatar_a"], 0.96, 0.8)
        _snapshot("步骤3：A 同意后，系统再向 B 推送交友邀请", fixtures)

        with connect() as db:
            invitation_b = db.execute("SELECT id FROM user_notifications WHERE recipient_user_id=%s AND friendship_id=%s AND notification_type='friendship_invitation'", (fixtures["user_b"], friendship_id)).fetchone()["id"]
        service.get_notification(fixtures["user_b"], str(invitation_b))
        service.decide_friendship(fixtures["user_b"], str(invitation_b), "accepted")
        _snapshot("步骤4：B 查看并同意，关系变为 accepted 并生成双方成功通知", fixtures)
        print("\n演示完成，临时 fixture:")
        print(json.dumps(fixtures | {"friendship_id": friendship_id}, ensure_ascii=False, indent=2))
    finally:
        if not args.keep:
            _cleanup(fixtures)
            print("\n已清理 demo-friendship-* 临时用户及其关联数据。")
        else:
            print("\n已保留临时数据；可使用上面的 UUID 在 PostgreSQL 中继续查询。")


if __name__ == "__main__":
    main()
