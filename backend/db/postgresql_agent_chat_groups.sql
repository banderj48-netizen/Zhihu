-- Agent 聊天组索引表：一次双 Agent 对话运行对应一组聊天
BEGIN;

CREATE TABLE IF NOT EXISTS public.agent_chat_groups (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    chat_no varchar(64) NOT NULL UNIQUE,
    dialogue_run_id uuid NOT NULL UNIQUE REFERENCES public.agent_dialogue_runs(id) ON DELETE CASCADE,
    conversation_id uuid NOT NULL UNIQUE REFERENCES public.chat_conversations(id) ON DELETE CASCADE,
    initiator_avatar_id uuid NOT NULL REFERENCES public.user_avatars(id) ON DELETE RESTRICT,
    invited_avatar_id uuid NOT NULL REFERENCES public.user_avatars(id) ON DELETE RESTRICT,
    initiator_user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE RESTRICT,
    invited_user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE RESTRICT,
    status varchar(32) NOT NULL DEFAULT 'running',
    started_at timestamptz NOT NULL DEFAULT now(),
    ended_at timestamptz,
    message_count integer NOT NULL DEFAULT 0,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT ck_agent_chat_groups_status CHECK (status IN ('running','completed','cancelled','failed')),
    CONSTRAINT ck_agent_chat_groups_distinct_avatars CHECK (initiator_avatar_id <> invited_avatar_id),
    CONSTRAINT ck_agent_chat_groups_time CHECK (ended_at IS NULL OR ended_at >= started_at)
);

COMMENT ON TABLE public.agent_chat_groups IS '一次双 Agent 函数调用对应的一组聊天索引';
COMMENT ON COLUMN public.agent_chat_groups.chat_no IS '对用户公开的唯一聊天号';
COMMENT ON COLUMN public.agent_chat_groups.dialogue_run_id IS '关联的 LangGraph 对话运行';
COMMENT ON COLUMN public.agent_chat_groups.conversation_id IS '关联的真实消息会话';
COMMENT ON COLUMN public.agent_chat_groups.initiator_avatar_id IS '发起聊天的数字分身';
COMMENT ON COLUMN public.agent_chat_groups.invited_avatar_id IS '被邀请聊天的数字分身';
COMMENT ON COLUMN public.agent_chat_groups.message_count IS '当前聊天组有效消息数量';
COMMENT ON COLUMN public.agent_chat_groups.metadata IS '场景、话题和结束原因等扩展信息';

CREATE INDEX IF NOT EXISTS idx_agent_chat_groups_initiator_user ON public.agent_chat_groups(initiator_user_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_chat_groups_invited_user ON public.agent_chat_groups(invited_user_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_chat_groups_initiator_avatar ON public.agent_chat_groups(initiator_avatar_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_chat_groups_invited_avatar ON public.agent_chat_groups(invited_avatar_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_chat_groups_status_time ON public.agent_chat_groups(status, started_at DESC);

COMMIT;
