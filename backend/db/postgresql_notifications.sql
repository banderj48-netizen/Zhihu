-- ============================================================
-- 通知、交友确认与陌生回答事实表
-- 使用方式：连接 zhihu 数据库后执行；前置脚本为画像、聊天、对话脚本。
-- ============================================================
BEGIN;

CREATE TABLE IF NOT EXISTS public.agent_unknown_responses (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    avatar_id uuid NOT NULL REFERENCES public.user_avatars(id) ON DELETE CASCADE,
    dialogue_run_id uuid REFERENCES public.agent_dialogue_runs(id) ON DELETE SET NULL,
    conversation_id uuid REFERENCES public.chat_conversations(id) ON DELETE SET NULL,
    chat_message_id uuid REFERENCES public.chat_messages(id) ON DELETE SET NULL,
    question text NOT NULL,
    agent_answer text NOT NULL,
    retrieval_threshold numeric(6,5) NOT NULL DEFAULT 0.50000,
    top_relevance_score numeric(6,5),
    retrieval_meta jsonb NOT NULL DEFAULT '{}'::jsonb,
    feedback_status varchar(24) NOT NULL DEFAULT 'pending',
    user_feedback varchar(16),
    feedback_text text,
    feedback_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT ck_unknown_feedback_status CHECK (feedback_status IN ('pending','accepted','rejected','applied','failed')),
    CONSTRAINT ck_unknown_feedback_value CHECK (user_feedback IS NULL OR user_feedback IN ('expected','unexpected')),
    CONSTRAINT ck_unknown_threshold CHECK (retrieval_threshold BETWEEN 0 AND 1),
    CONSTRAINT ck_unknown_score CHECK (top_relevance_score IS NULL OR top_relevance_score BETWEEN 0 AND 1)
);
COMMENT ON TABLE public.agent_unknown_responses IS '数字分身未检索到相关记忆时的回答事实和用户反馈';
COMMENT ON COLUMN public.agent_unknown_responses.question IS '触发回答的原始问题';
COMMENT ON COLUMN public.agent_unknown_responses.agent_answer IS '数字分身实际输出的回答';
COMMENT ON COLUMN public.agent_unknown_responses.retrieval_meta IS '检索数量、阈值和候选分数等审计信息';
COMMENT ON COLUMN public.agent_unknown_responses.feedback_status IS '反馈状态：待处理、符合预期、不符合预期、已应用或失败';

CREATE TABLE IF NOT EXISTS public.avatar_friendships (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    dialogue_run_id uuid NOT NULL UNIQUE REFERENCES public.agent_dialogue_runs(id) ON DELETE CASCADE,
    user_a_id uuid NOT NULL REFERENCES public.users(id) ON DELETE RESTRICT,
    user_b_id uuid NOT NULL REFERENCES public.users(id) ON DELETE RESTRICT,
    avatar_a_id uuid NOT NULL REFERENCES public.user_avatars(id) ON DELETE RESTRICT,
    avatar_b_id uuid NOT NULL REFERENCES public.user_avatars(id) ON DELETE RESTRICT,
    evaluation_id uuid REFERENCES public.agent_dialogue_evaluations(id) ON DELETE SET NULL,
    score numeric(5,4) NOT NULL,
    threshold numeric(5,4) NOT NULL,
    match_summary text,
    user_a_decision varchar(16) NOT NULL DEFAULT 'pending',
    user_b_decision varchar(16) NOT NULL DEFAULT 'pending',
    user_a_decided_at timestamptz,
    user_b_decided_at timestamptz,
    status varchar(24) NOT NULL DEFAULT 'pending',
    connected_at timestamptz,
    closed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT ck_friendship_users_distinct CHECK (user_a_id <> user_b_id),
    CONSTRAINT ck_friendship_avatars_distinct CHECK (avatar_a_id <> avatar_b_id),
    CONSTRAINT ck_friendship_score CHECK (score BETWEEN 0 AND 1),
    CONSTRAINT ck_friendship_threshold CHECK (threshold BETWEEN 0 AND 1),
    CONSTRAINT ck_friendship_decisions CHECK (user_a_decision IN ('pending','accepted','rejected') AND user_b_decision IN ('pending','accepted','rejected')),
    CONSTRAINT ck_friendship_status CHECK (status IN ('pending','accepted','rejected_by_a','rejected_by_b','expired','cancelled'))
);
COMMENT ON TABLE public.avatar_friendships IS '两个数字分身完成高质量对话后的交友确认关系';
COMMENT ON COLUMN public.avatar_friendships.dialogue_run_id IS '产生本次交友建议的双 Agent 对话批次';
COMMENT ON COLUMN public.avatar_friendships.user_a_decision IS 'A 用户的决定：待处理、同意或拒绝';
COMMENT ON COLUMN public.avatar_friendships.user_b_decision IS 'B 用户的决定：待处理、同意或拒绝';
COMMENT ON COLUMN public.avatar_friendships.status IS '关系状态；双方均同意后才为 accepted';

CREATE UNIQUE INDEX IF NOT EXISTS uq_avatar_friendships_user_pair_run
    ON public.avatar_friendships (LEAST(user_a_id, user_b_id), GREATEST(user_a_id, user_b_id), dialogue_run_id);
CREATE INDEX IF NOT EXISTS idx_avatar_friendships_user_a ON public.avatar_friendships(user_a_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_avatar_friendships_user_b ON public.avatar_friendships(user_b_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_avatar_friendships_status ON public.avatar_friendships(status, updated_at DESC);

CREATE TABLE IF NOT EXISTS public.user_notifications (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    recipient_user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    notification_type varchar(40) NOT NULL,
    title varchar(200) NOT NULL,
    body text NOT NULL,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    source_dialogue_run_id uuid REFERENCES public.agent_dialogue_runs(id) ON DELETE SET NULL,
    source_chat_message_id uuid REFERENCES public.chat_messages(id) ON DELETE SET NULL,
    friendship_id uuid REFERENCES public.avatar_friendships(id) ON DELETE SET NULL,
    unknown_response_id uuid REFERENCES public.agent_unknown_responses(id) ON DELETE SET NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    read_at timestamptz,
    action_at timestamptz,
    status varchar(24) NOT NULL DEFAULT 'unread',
    expires_at timestamptz,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT ck_user_notifications_type CHECK (notification_type IN ('friendship_invitation','friendship_connected','unknown_agent_response','system')),
    CONSTRAINT ck_user_notifications_status CHECK (status IN ('unread','read','accepted','rejected','consumed','expired'))
);
COMMENT ON TABLE public.user_notifications IS '所有用户共用的系统通知和数字分身反馈消息表';
COMMENT ON COLUMN public.user_notifications.recipient_user_id IS '通知接收用户';
COMMENT ON COLUMN public.user_notifications.notification_type IS '通知类型：交友邀请、交友成功、陌生回答或系统通知';
COMMENT ON COLUMN public.user_notifications.payload IS '弹窗所需的结构化快照，避免画像变更影响历史消息';
COMMENT ON COLUMN public.user_notifications.status IS '消息状态：未读、已读、已同意、已拒绝、已消费或已过期';

CREATE INDEX IF NOT EXISTS idx_user_notifications_recipient_status_time ON public.user_notifications(recipient_user_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_user_notifications_recipient_read_time ON public.user_notifications(recipient_user_id, read_at, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_user_notifications_dialogue ON public.user_notifications(source_dialogue_run_id);
CREATE INDEX IF NOT EXISTS idx_user_notifications_friendship ON public.user_notifications(friendship_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_user_notifications_friendship_invite ON public.user_notifications(recipient_user_id, friendship_id, notification_type) WHERE notification_type = 'friendship_invitation';
CREATE UNIQUE INDEX IF NOT EXISTS uq_user_notifications_unknown_response ON public.user_notifications(recipient_user_id, unknown_response_id, notification_type) WHERE notification_type = 'unknown_agent_response';
CREATE UNIQUE INDEX IF NOT EXISTS uq_user_notifications_friendship_connected ON public.user_notifications(recipient_user_id, friendship_id, notification_type) WHERE notification_type = 'friendship_connected';

COMMIT;
