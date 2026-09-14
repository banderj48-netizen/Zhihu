"""Best-effort Chroma synchronization worker for PostgreSQL outbox rows."""
from __future__ import annotations
from typing import Any
from db.database import connect
from agent.retrieval.service import index_memory, index_source_document_chunk, index_chat_message

async def sync_pending(vector_store: Any, *, limit: int = 50) -> dict[str, int]:
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
                    await index_memory(entity, vector_store, collection=row['collection'])
                elif row['entity_type'] == 'source_document': entity = db.execute("SELECT * FROM source_documents WHERE id=%s", (row['entity_id'],)).fetchone(); await index_source_document_chunk(entity, vector_store, collection=row['collection'])
                elif row['entity_type'] == 'chat_message': entity = db.execute("SELECT * FROM chat_messages WHERE id=%s", (row['entity_id'],)).fetchone(); await index_chat_message(entity, vector_store, collection=row['collection'])
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
