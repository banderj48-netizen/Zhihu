from __future__ import annotations
from typing import Any
from psycopg.types.json import Jsonb
from db.database import connect

class ChatRepository:
    def create_conversation(self, conversation_type="direct", title=None) -> str:
        with connect() as db:
            return str(db.execute("INSERT INTO chat_conversations(conversation_type,title) VALUES(%s,%s) RETURNING id",(conversation_type,title)).fetchone()["id"])
    def append_message(self, conversation_id:str, participant_id:str, content:str, *, client_message_id:str|None=None, message_type="text", metadata:dict|None=None) -> dict[str,Any]:
        with connect() as db:
            db.execute("SELECT id FROM chat_conversations WHERE id=%s FOR UPDATE", (conversation_id,))
            row=db.execute("SELECT COALESCE(MAX(sequence_no),0)+1 AS n FROM chat_messages WHERE conversation_id=%s",(conversation_id,)).fetchone()
            msg=db.execute("""INSERT INTO chat_messages(conversation_id,participant_id,sequence_no,client_message_id,message_type,content,metadata)
                VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(conversation_id,client_message_id) DO NOTHING RETURNING id,sequence_no,sent_at""",(conversation_id,participant_id,row["n"],client_message_id,message_type,content,Jsonb(metadata or {}))).fetchone()
            if not msg and client_message_id:
                msg=db.execute("SELECT id,sequence_no,sent_at FROM chat_messages WHERE conversation_id=%s AND client_message_id=%s", (conversation_id, client_message_id)).fetchone()
            if not msg:
                raise RuntimeError("消息写入失败")
            participant = db.execute("SELECT avatar_id FROM chat_participants WHERE id=%s", (participant_id,)).fetchone()
            if participant:
                db.execute("""INSERT INTO vector_sync_outbox(avatar_id,entity_type,entity_id,operation,collection,payload)
                    VALUES(%s,'chat_message',%s,'upsert','chat_messages',%s)
                    ON CONFLICT DO NOTHING""", (participant["avatar_id"], msg["id"], Jsonb({"message_id": str(msg["id"]), "avatar_id": str(participant["avatar_id"]), "conversation_id": conversation_id})))
            return {"message_id":str(msg["id"]),"sequence_no":msg["sequence_no"],"sent_at":msg["sent_at"].isoformat()}
