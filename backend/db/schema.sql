CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    deleted_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS avatars (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT,
    status TEXT NOT NULL DEFAULT 'not_started',
    current_version INTEGER,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    deleted_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS consents (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    scopes_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    status TEXT NOT NULL DEFAULT 'active',
    token_ref TEXT,
    granted_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS initialization_sessions (
    id TEXT PRIMARY KEY,
    avatar_id TEXT NOT NULL REFERENCES avatars(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'created',
    current_step TEXT NOT NULL DEFAULT 'created',
    assessment_status TEXT NOT NULL DEFAULT 'not_started',
    selected_scopes_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    failure_code TEXT,
    failure_message TEXT
);

CREATE TABLE IF NOT EXISTS import_jobs (
    id TEXT PRIMARY KEY,
    initialization_id TEXT NOT NULL REFERENCES initialization_sessions(id) ON DELETE CASCADE,
    consent_id TEXT REFERENCES consents(id) ON DELETE SET NULL,
    provider TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    progress INTEGER NOT NULL DEFAULT 0,
    cursor TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0,
    idempotency_key TEXT NOT NULL UNIQUE,
    error_code TEXT,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS source_documents (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    consent_id TEXT REFERENCES consents(id) ON DELETE SET NULL,
    provider TEXT NOT NULL,
    content_type TEXT NOT NULL,
    source_url TEXT NOT NULL,
    title TEXT,
    author_id TEXT,
    source_created_at TIMESTAMPTZ,
    raw_payload JSONB NOT NULL,
    raw_hash TEXT NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL,
    deleted_at TIMESTAMPTZ,
    UNIQUE(user_id, provider, source_url, raw_hash)
);

CREATE TABLE IF NOT EXISTS evidence_chunks (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES source_documents(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    text TEXT NOT NULL,
    char_start INTEGER,
    char_end INTEGER,
    section_title TEXT,
    text_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    UNIQUE(document_id, chunk_index)
);

CREATE TABLE IF NOT EXISTS profile_candidates (
    id TEXT PRIMARY KEY,
    avatar_id TEXT NOT NULL REFERENCES avatars(id) ON DELETE CASCADE,
    candidate_type TEXT NOT NULL,
    payload_json JSONB NOT NULL,
    status TEXT NOT NULL DEFAULT 'unconfirmed',
    confidence REAL,
    privacy TEXT NOT NULL DEFAULT 'private',
    share BOOLEAN NOT NULL DEFAULT FALSE,
    source_ids_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    deleted_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS profile_reviews (
    id TEXT PRIMARY KEY,
    avatar_id TEXT NOT NULL REFERENCES avatars(id) ON DELETE CASCADE,
    candidate_id TEXT REFERENCES profile_candidates(id) ON DELETE SET NULL,
    action TEXT NOT NULL,
    before_json JSONB,
    after_json JSONB,
    reason TEXT,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS personality_assessments (
    id TEXT PRIMARY KEY,
    avatar_id TEXT NOT NULL REFERENCES avatars(id) ON DELETE CASCADE,
    instrument_version TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'incomplete',
    raw_answers_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    scores_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    confidence REAL,
    confidence_interval_json JSONB,
    validity_json JSONB,
    source_mix_json JSONB,
    skipped BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    avatar_id TEXT NOT NULL REFERENCES avatars(id) ON DELETE CASCADE,
    depth TEXT NOT NULL CHECK (depth IN ('deep', 'middle', 'shallow')),
    memory_type TEXT NOT NULL,
    payload_json JSONB NOT NULL,
    status TEXT NOT NULL DEFAULT 'unconfirmed',
    confidence REAL,
    privacy TEXT NOT NULL DEFAULT 'private',
    share BOOLEAN NOT NULL DEFAULT FALSE,
    valid_from TIMESTAMPTZ,
    valid_until TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    deleted_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS memory_evidences (
    memory_id TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    evidence_id TEXT NOT NULL REFERENCES evidence_chunks(id) ON DELETE CASCADE,
    relation TEXT NOT NULL DEFAULT 'supports',
    PRIMARY KEY(memory_id, evidence_id)
);

CREATE TABLE IF NOT EXISTS avatar_versions (
    id TEXT PRIMARY KEY,
    avatar_id TEXT NOT NULL REFERENCES avatars(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    snapshot_json JSONB NOT NULL,
    card_json JSONB,
    created_at TIMESTAMPTZ NOT NULL,
    published_at TIMESTAMPTZ,
    UNIQUE(avatar_id, version)
);

CREATE TABLE IF NOT EXISTS agent_events (
    id TEXT PRIMARY KEY,
    avatar_id TEXT NOT NULL REFERENCES avatars(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    payload_json JSONB NOT NULL,
    contract_version TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_events (
    id TEXT PRIMARY KEY,
    user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
    avatar_id TEXT REFERENCES avatars(id) ON DELETE SET NULL,
    event_type TEXT NOT NULL,
    target_type TEXT,
    target_id TEXT,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_avatars_user ON avatars(user_id);
CREATE INDEX IF NOT EXISTS idx_consents_user_status ON consents(user_id, status);
CREATE INDEX IF NOT EXISTS idx_init_avatar_status ON initialization_sessions(avatar_id, status);
CREATE INDEX IF NOT EXISTS idx_jobs_init_status ON import_jobs(initialization_id, status);
CREATE INDEX IF NOT EXISTS idx_documents_user_type ON source_documents(user_id, content_type);
CREATE INDEX IF NOT EXISTS idx_evidence_document ON evidence_chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_candidates_avatar_status ON profile_candidates(avatar_id, status);
CREATE INDEX IF NOT EXISTS idx_memories_avatar_depth ON memories(avatar_id, depth);
CREATE INDEX IF NOT EXISTS idx_memories_avatar_status ON memories(avatar_id, status);
CREATE INDEX IF NOT EXISTS idx_versions_avatar ON avatar_versions(avatar_id, version);
CREATE INDEX IF NOT EXISTS idx_agent_events_avatar_time ON agent_events(avatar_id, created_at);
CREATE INDEX IF NOT EXISTS idx_audit_avatar_time ON audit_events(avatar_id, created_at);
