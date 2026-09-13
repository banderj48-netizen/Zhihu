-- PostgreSQL migration 2: assessment result snapshots and idempotency keys.
ALTER TABLE personality_assessments ADD COLUMN result_json JSONB;
ALTER TABLE personality_assessments ADD COLUMN request_key TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS idx_personality_assessment_request
    ON personality_assessments(avatar_id, request_key)
    WHERE request_key IS NOT NULL;
