-- PostgreSQL migration 3: user domain interests and self-reported expertise.
CREATE TABLE IF NOT EXISTS avatar_domain_selections (
    id TEXT PRIMARY KEY,
    avatar_id TEXT NOT NULL REFERENCES avatars(id) ON DELETE CASCADE,
    domain_id TEXT NOT NULL,
    selection_type TEXT NOT NULL CHECK (selection_type IN ('interest','expertise')),
    interest_level INTEGER NOT NULL DEFAULT 1 CHECK (interest_level BETWEEN 0 AND 3),
    proficiency TEXT CHECK (proficiency IS NULL OR proficiency IN ('novice','familiar','working','advanced','unknown')),
    notes TEXT,
    revision INTEGER NOT NULL,
    privacy TEXT NOT NULL DEFAULT 'private',
    share BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    deleted_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_domain_selection_avatar ON avatar_domain_selections(avatar_id, selection_type, deleted_at);
CREATE INDEX IF NOT EXISTS idx_domain_selection_domain ON avatar_domain_selections(domain_id);
