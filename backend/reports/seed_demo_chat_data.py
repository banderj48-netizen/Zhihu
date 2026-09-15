"""为指定用户生成可在相遇页展示的真实聊天测试数据。"""
from __future__ import annotations

import argparse
from uuid import uuid4
from db.database import connect
from psycopg.types.json import Jsonb

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--external-id", default="2078923165116511375")
    parser.add_argument("--count", type=int, default=3)
    args = parser.parse_args()
    with connect() as db:
        me = db.execute("""SELECT u.id user_id,a.id avatar_id,a.display_name FROM users u JOIN user_avatars a ON a.user_id=u.id WHERE u.external_id=%s AND a.status='ready' LIMIT 1""", (args.external_id,)).fetchone()
        if not me: raise SystemExit(f"未找到用户或 ready 分身: {args.external_id}")
        peers = db.execute("""SELECT u.id user_id,a.id avatar_id,a.display_name FROM users u JOIN user_avatars a ON a.user_id=u.id WHERE u.id<>%s AND a.status='ready' ORDER BY a.updated_at DESC LIMIT %s""", (me["user_id"], args.count)).fetchall()
        for index, peer in enumerate(peers, 1):
            run_id, conversation_id = uuid4(), uuid4()
            db.execute("INSERT INTO chat_conversations(id,conversation_type,title,status,started_at,ended_at,metadata) VALUES(%s,'direct',%s,'ended',now()-interval '1 day',now()-interval '1 day',%s)", (conversation_id, f"与{peer['display_name'] or '相遇用户'}的对话", Jsonb({"seed": True})))
            db.execute("INSERT INTO agent_dialogue_runs(id,conversation_id,avatar_a_id,avatar_b_id,user_a_id,user_b_id,status,current_turn,max_rounds,started_at,ended_at,metadata) VALUES(%s,%s,%s,%s,%s,%s,'completed',3,3,now()-interval '1 day',now()-interval '1 day',%s)", (run_id, conversation_id, me["avatar_id"], peer["avatar_id"], me["user_id"], peer["user_id"], Jsonb({"seed": True, "scene_id": ["cafe","library","bar"][index % 3]})))
            pa = db.execute("INSERT INTO chat_participants(conversation_id,avatar_id,display_name) VALUES(%s,%s,%s) RETURNING id", (conversation_id, me["avatar_id"], me["display_name"] or "我的看山")).fetchone()["id"]
            pb = db.execute("INSERT INTO chat_participants(conversation_id,avatar_id,display_name) VALUES(%s,%s,%s) RETURNING id", (conversation_id, peer["avatar_id"], peer["display_name"] or f"相遇用户{index}")).fetchone()["id"]
            messages = [(pa, "最近在关注什么话题？"), (pb, "我最近在想，技术怎样才能真正改善普通人的日常体验。"), (pa, "这个角度很有意思，我也更在意具体而持久的改变。"), (pb, "那下次可以继续聊聊各自观察到的案例。")]
            for seq, (participant, content) in enumerate(messages, 1):
                db.execute("INSERT INTO chat_messages(conversation_id,participant_id,sequence_no,client_message_id,content,sent_at,metadata) VALUES(%s,%s,%s,%s,%s,now()-(%s * interval '1 minute'),%s)", (conversation_id, participant, seq, f"seed-{run_id}-{seq}", content, 40-seq*7, Jsonb({"seed": True})))
            chat_no = f"chat_seed_{uuid4().hex[:20]}"
            db.execute("INSERT INTO agent_chat_groups(chat_no,dialogue_run_id,conversation_id,initiator_avatar_id,invited_avatar_id,initiator_user_id,invited_user_id,status,started_at,ended_at,message_count,metadata,processing_status,processed_at,visible_at) VALUES(%s,%s,%s,%s,%s,%s,%s,'completed',now()-interval '1 day',now()-interval '1 day' + interval '30 minutes',4,%s,'ready',now(),now())", (chat_no, run_id, conversation_id, me["avatar_id"], peer["avatar_id"], me["user_id"], peer["user_id"], Jsonb({"seed": True, "source": "seed_demo_chat_data"})))
            print(chat_no)

if __name__ == "__main__":
    main()
