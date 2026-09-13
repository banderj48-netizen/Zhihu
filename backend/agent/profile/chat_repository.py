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
                VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(conversation_id,client_message_id) DO UPDATE SET content=EXCLUDED.content RETURNING id,sequence_no,sent_at""",(conversation_id,participant_id,row["n"],client_message_id,message_type,content,Jsonb(metadata or {}))).fetchone()
            return {"message_id":str(msg["id"]),"sequence_no":msg["sequence_no"],"sent_at":msg["sent_at"].isoformat()}
