-- LangGraph 双 Agent 对话运行状态和评判结果
BEGIN;

CREATE TABLE IF NOT EXISTS public.agent_dialogue_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id uuid NOT NULL UNIQUE REFERENCES public.chat_conversations(id) ON DELETE CASCADE,
    avatar_a_id uuid NOT NULL REFERENCES public.user_avatars(id) ON DELETE RESTRICT,
    avatar_b_id uuid NOT NULL REFERENCES public.user_avatars(id) ON DELETE RESTRICT,
    user_a_id uuid NOT NULL REFERENCES public.users(id) ON DELETE RESTRICT,
    user_b_id uuid NOT NULL REFERENCES public.users(id) ON DELETE RESTRICT,
    status varchar(32) NOT NULL DEFAULT 'queued',
    current_turn integer NOT NULL DEFAULT 0,
    max_rounds integer NOT NULL DEFAULT 10,
    started_at timestamptz,
    ended_at timestamptz,
    last_error text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT ck_agent_dialogue_status CHECK (status IN ('queued','running','evaluating','completed','evaluation_failed','cancelled','failed')),
    CONSTRAINT ck_agent_dialogue_rounds CHECK (max_rounds BETWEEN 1 AND 10),
    CONSTRAINT ck_agent_dialogue_distinct_avatars CHECK (avatar_a_id <> avatar_b_id)
);

COMMENT ON TABLE public.agent_dialogue_runs IS '双数字分身对话运行状态表';
COMMENT ON COLUMN public.agent_dialogue_runs.id IS '对话运行唯一标识';
COMMENT ON COLUMN public.agent_dialogue_runs.conversation_id IS '对应的聊天会话';
COMMENT ON COLUMN public.agent_dialogue_runs.avatar_a_id IS '发起方数字分身';
COMMENT ON COLUMN public.agent_dialogue_runs.avatar_b_id IS '被邀请方数字分身';
COMMENT ON COLUMN public.agent_dialogue_runs.user_a_id IS '发起方用户';
COMMENT ON COLUMN public.agent_dialogue_runs.user_b_id IS '被邀请方用户';
COMMENT ON COLUMN public.agent_dialogue_runs.status IS '运行状态';
COMMENT ON COLUMN public.agent_dialogue_runs.current_turn IS '当前完成的轮次';
COMMENT ON COLUMN public.agent_dialogue_runs.max_rounds IS '最大对话轮次，最多10轮';
COMMENT ON COLUMN public.agent_dialogue_runs.metadata IS '图线程、模型和配置等扩展信息';

CREATE TABLE IF NOT EXISTS public.agent_dialogue_evaluations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    dialogue_run_id uuid NOT NULL UNIQUE REFERENCES public.agent_dialogue_runs(id) ON DELETE CASCADE,
    evaluator_model varchar(128) NOT NULL,
    score numeric(5,4) NOT NULL,
    great_score numeric(5,4) NOT NULL,
    summary text,
    dimensions jsonb NOT NULL DEFAULT '{}'::jsonb,
    raw_result jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_dialogue_evaluation_score CHECK (score BETWEEN 0 AND 1),
    CONSTRAINT ck_dialogue_evaluation_threshold CHECK (great_score BETWEEN 0 AND 1)
);

COMMENT ON TABLE public.agent_dialogue_evaluations IS '双 Agent 对话契合度评判结果';
COMMENT ON COLUMN public.agent_dialogue_evaluations.id IS '评判记录唯一标识';
COMMENT ON COLUMN public.agent_dialogue_evaluations.dialogue_run_id IS '对应的双 Agent 对话运行';
COMMENT ON COLUMN public.agent_dialogue_evaluations.evaluator_model IS '评判模型名称';
COMMENT ON COLUMN public.agent_dialogue_evaluations.score IS '总体契合度，范围0到1';
COMMENT ON COLUMN public.agent_dialogue_evaluations.great_score IS '触发推送的阈值';
COMMENT ON COLUMN public.agent_dialogue_evaluations.summary IS '评判摘要';
COMMENT ON COLUMN public.agent_dialogue_evaluations.dimensions IS '分项评分，例如兴趣、价值观和沟通质量';
COMMENT ON COLUMN public.agent_dialogue_evaluations.raw_result IS '评判模型原始结构化结果';

CREATE INDEX IF NOT EXISTS idx_agent_dialogue_runs_status ON public.agent_dialogue_runs(status, started_at);
CREATE INDEX IF NOT EXISTS idx_agent_dialogue_runs_avatars ON public.agent_dialogue_runs(avatar_a_id, avatar_b_id);

COMMIT;
