-- Optional companion tables for PostgreSQL + Chroma eventual synchronization.
BEGIN;
CREATE TABLE IF NOT EXISTS public.vector_sync_outbox (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    avatar_id uuid NOT NULL REFERENCES public.user_avatars(id) ON DELETE CASCADE,
    entity_type varchar(32) NOT NULL,
    entity_id uuid NOT NULL,
    operation varchar(16) NOT NULL,
    collection varchar(64) NOT NULL,
    status varchar(16) NOT NULL DEFAULT 'pending',
    attempt_count integer NOT NULL DEFAULT 0,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    last_error text,
    available_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now(),
    processed_at timestamptz,
    CONSTRAINT ck_vector_sync_operation CHECK (operation IN ('upsert','delete')),
    CONSTRAINT ck_vector_sync_status CHECK (status IN ('pending','processing','succeeded','failed'))
);
CREATE INDEX IF NOT EXISTS idx_vector_sync_pending ON public.vector_sync_outbox(status,available_at);
CREATE UNIQUE INDEX IF NOT EXISTS uq_vector_sync_entity ON public.vector_sync_outbox(entity_type,entity_id,operation) WHERE status IN ('pending','processing');
COMMIT;
