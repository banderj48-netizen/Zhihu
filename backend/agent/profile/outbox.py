"""PostgreSQL outbox 到 Chroma 的异步同步 worker。"""
from __future__ import annotations
import asyncio
from typing import Any
from db.database import connect
from agent.retrieval.service import index_memory, index_source_document_chunk, index_chat_message


def enqueue_missing_vectors(*, limit: int = 1000) -> int:
    """为历史画像、原始资料和聊天消息补建待同步任务，保证旧数据可被向量检索。"""
    safe_limit = max(1, min(limit, 10000))
    inserted = 0
    with connect() as db:
        for entity_type, collection, table, avatar_column in (
            ("avatar_memory", "avatar_memories", "avatar_memories", "avatar_id"),
            ("source_document", "source_documents", "source_documents", "avatar_id"),
        ):
            inserted += db.execute(f"""
                INSERT INTO vector_sync_outbox(avatar_id,entity_type,entity_id,operation,collection,payload)
                SELECT {avatar_column}, %s, id, 'upsert', %s, jsonb_build_object('entity_id',id::text,'avatar_id',{avatar_column}::text)
                FROM {table} e
                WHERE NOT EXISTS (SELECT 1 FROM vector_sync_outbox o WHERE o.entity_type=%s AND o.entity_id=e.id AND o.operation='upsert')
                LIMIT %s
            """, (entity_type, collection, entity_type, safe_limit)).rowcount
        inserted += db.execute(f"""
            INSERT INTO vector_sync_outbox(avatar_id,entity_type,entity_id,operation,collection,payload)
            SELECT p.avatar_id, 'chat_message', m.id, 'upsert', 'chat_messages', jsonb_build_object('message_id',m.id::text,'avatar_id',p.avatar_id::text,'conversation_id',m.conversation_id::text)
            FROM chat_messages m JOIN chat_participants p ON p.id=m.participant_id
            WHERE m.deleted_at IS NULL
              AND NOT EXISTS (SELECT 1 FROM vector_sync_outbox o WHERE o.entity_type='chat_message' AND o.entity_id=m.id AND o.operation='upsert')
            LIMIT %s
        """, (safe_limit,)).rowcount
    return inserted


async def run_sync_loop(vector_store: Any, stop_event: asyncio.Event, *, interval_seconds: float = 2.0, batch_size: int = 50) -> None:
    """在应用进程内异步消费向量 outbox，不依赖 MQ。"""
    while not stop_event.is_set():
        try:
            # 同步函数只操作短事务，向量网络调用在 sync_pending 内异步执行。
            await sync_pending(vector_store, limit=batch_size)
        except Exception:
            # 后台同步失败不阻断 API；失败任务会保留在 outbox 等待下次重试。
            pass
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=max(0.2, interval_seconds))
        except asyncio.TimeoutError:
            continue

async def sync_pending(vector_store: Any, *, limit: int = 50) -> dict[str, int]:
    """消费一批 outbox 任务，并把失败任务安排为指数退避重试。"""
    from agent.adapters.chroma_factory import embedding_model_name

    model_name = embedding_model_name()
    processed = failed = 0
    # Claim rows in a short transaction, then perform network/vector work outside it.
    with connect() as db:
        rows = db.execute("""SELECT id,entity_type,entity_id,collection
            FROM vector_sync_outbox
            WHERE status IN ('pending','failed') AND available_at<=now()
            ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT %s""", (max(1,min(limit,500)),)).fetchall()
        for row in rows:
                db.execute("UPDATE vector_sync_outbox SET status='processing',attempt_count=attempt_count+1 WHERE id=%s", (row['id'],))
    for row in rows:
        try:
            with connect() as db:
                entity = None
                if row['entity_type'] == 'avatar_memory':
                    entity = db.execute("SELECT * FROM avatar_memories WHERE id=%s AND status IN ('confirmed','unconfirmed') AND privacy IN ('public','private')", (row['entity_id'],)).fetchone()
                    if not entity:
                        # Rejected/expired/private records must never enter the
                        # vector index.  Mark this work item complete because
                        # there is nothing left to retry.
                        try:
                            await vector_store.delete(row['collection'], [str(row['entity_id'])])
                        except Exception:
                            pass
                        with connect() as clean_db:
                            clean_db.execute("UPDATE vector_sync_outbox SET status='succeeded',processed_at=now(),last_error='skipped: memory not indexable' WHERE id=%s", (row['id'],))
                        processed += 1
                        continue
                    await index_memory(entity, vector_store, collection=row['collection'], embedding_model=model_name)
                elif row['entity_type'] == 'source_document': entity = db.execute("SELECT * FROM source_documents WHERE id=%s", (row['entity_id'],)).fetchone(); await index_source_document_chunk(entity, vector_store, collection=row['collection'], embedding_model=model_name)
                elif row['entity_type'] == 'chat_message': entity = db.execute("SELECT * FROM chat_messages WHERE id=%s", (row['entity_id'],)).fetchone(); await index_chat_message(entity, vector_store, collection=row['collection'], embedding_model=model_name)
                else: raise ValueError('unsupported entity type')
                if not entity: raise ValueError('entity no longer exists')
            with connect() as db: db.execute("UPDATE vector_sync_outbox SET status='succeeded',processed_at=now(),last_error=NULL WHERE id=%s", (row['id'],)); processed += 1
        except Exception as exc:
            with connect() as db:
                db.execute("""UPDATE vector_sync_outbox
                    SET status='failed',last_error=%s,
                        available_at=now() + make_interval(secs => LEAST(3600, POWER(2, attempt_count)::int))
                    WHERE id=%s""", (str(exc)[:1000],row['id'])); failed += 1
    return {'processed':processed,'failed':failed}
