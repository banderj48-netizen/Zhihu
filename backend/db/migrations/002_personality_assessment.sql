ALTER TABLE personality_assessments ADD COLUMN result_json TEXT;
ALTER TABLE personality_assessments ADD COLUMN request_key TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS idx_personality_assessment_request
    ON personality_assessments(avatar_id, request_key);
