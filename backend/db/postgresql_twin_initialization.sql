BEGIN;

CREATE TABLE IF NOT EXISTS avatar_initialization_sessions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    import_job_id text,
    status varchar(32) NOT NULL DEFAULT 'created',
    current_step varchar(64) NOT NULL DEFAULT 'created',
    input_data jsonb NOT NULL DEFAULT '{}'::jsonb,
    generated_profile jsonb NOT NULL DEFAULT '{}'::jsonb,
    error_message text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    CONSTRAINT uq_avatar_initialization_user UNIQUE(user_id),
    CONSTRAINT ck_avatar_initialization_status CHECK (status IN ('created','importing','personality_pending','domain_pending','opinion_questions_pending','social_questions_pending','generating_profile','review','completed','failed'))
);
COMMENT ON TABLE avatar_initialization_sessions IS '数字分身初始化流程状态';
COMMENT ON COLUMN avatar_initialization_sessions.input_data IS '性格、领域和问卷等用户输入';
COMMENT ON COLUMN avatar_initialization_sessions.generated_profile IS 'LLM 生成的画像候选';

CREATE TABLE IF NOT EXISTS avatar_mind_reading_feedback (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    avatar_id uuid NOT NULL REFERENCES user_avatars(id) ON DELETE CASCADE,
    dialogue_run_id uuid REFERENCES agent_dialogue_runs(id) ON DELETE SET NULL,
    question jsonb NOT NULL,
    selected_option_id text,
    agent_option_id text,
    is_match boolean,
    personality_dimension text,
    status varchar(24) NOT NULL DEFAULT 'pending',
    created_at timestamptz NOT NULL DEFAULT now(),
    answered_at timestamptz,
    CONSTRAINT ck_mind_feedback_status CHECK (status IN ('pending','answered','applied'))
);
COMMENT ON TABLE avatar_mind_reading_feedback IS '无记忆命中后的心灵感应题及反馈';
COMMENT ON COLUMN avatar_mind_reading_feedback.question IS '题干和候选选项';

CREATE TABLE IF NOT EXISTS avatar_personality_adjustments (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    avatar_id uuid NOT NULL REFERENCES user_avatars(id) ON DELETE CASCADE,
    dimension text NOT NULL,
    direction varchar(16) NOT NULL,
    evidence_count integer NOT NULL DEFAULT 0,
    before_value numeric(8,4),
    after_value numeric(8,4),
    reason text,
    created_at timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE avatar_personality_adjustments IS '性格反馈累计与调整记录';

CREATE INDEX IF NOT EXISTS idx_avatar_init_status ON avatar_initialization_sessions(status, updated_at);
CREATE INDEX IF NOT EXISTS idx_mind_feedback_avatar ON avatar_mind_reading_feedback(avatar_id, status);

COMMIT;
