-- 聊天组处理完成后的用户已读状态
-- 依赖：postgresql_agent_chat_groups.sql、postgresql_zhihu_schema.sql
BEGIN;

ALTER TABLE public.agent_chat_groups
    ADD COLUMN IF NOT EXISTS processing_status varchar(16) NOT NULL DEFAULT 'processing';
ALTER TABLE public.agent_chat_groups
    ADD COLUMN IF NOT EXISTS processed_at timestamptz;
ALTER TABLE public.agent_chat_groups
    ADD COLUMN IF NOT EXISTS visible_at timestamptz;

-- 对脚本执行前已经完成的历史聊天做一次安全回填，使其可正常出现在历史列表。
UPDATE public.agent_chat_groups
   SET processing_status = 'ready',
       processed_at = COALESCE(processed_at, ended_at, now()),
       visible_at = COALESCE(visible_at, ended_at, now())
 WHERE status IN ('completed', 'cancelled')
   AND processing_status = 'processing';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ck_agent_chat_groups_processing_status'
    ) THEN
        ALTER TABLE public.agent_chat_groups
            ADD CONSTRAINT ck_agent_chat_groups_processing_status
            CHECK (processing_status IN ('processing', 'ready', 'failed'));
    END IF;
END $$;

COMMENT ON COLUMN public.agent_chat_groups.processing_status IS '聊天事实处理状态；ready后才展示给用户';
COMMENT ON COLUMN public.agent_chat_groups.processed_at IS '完整消息与元数据处理完成时间';
COMMENT ON COLUMN public.agent_chat_groups.visible_at IS '允许出现在用户聊天记录列表的时间';

CREATE INDEX IF NOT EXISTS idx_agent_chat_groups_visible
    ON public.agent_chat_groups(processing_status, visible_at DESC);

CREATE TABLE IF NOT EXISTS public.agent_chat_group_reads (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    chat_group_id uuid NOT NULL REFERENCES public.agent_chat_groups(id) ON DELETE CASCADE,
    user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    first_read_at timestamptz,
    last_read_at timestamptz,
    CONSTRAINT uq_agent_chat_group_reads_group_user UNIQUE (chat_group_id, user_id)
);

COMMENT ON TABLE public.agent_chat_group_reads IS '用户查看 Agent 聊天组的已读记录';
COMMENT ON COLUMN public.agent_chat_group_reads.chat_group_id IS '聊天组唯一标识';
COMMENT ON COLUMN public.agent_chat_group_reads.user_id IS '查看聊天记录的用户';
COMMENT ON COLUMN public.agent_chat_group_reads.first_read_at IS '首次查看时间';
COMMENT ON COLUMN public.agent_chat_group_reads.last_read_at IS '最近查看时间';

CREATE INDEX IF NOT EXISTS idx_agent_chat_group_reads_user
    ON public.agent_chat_group_reads(user_id, last_read_at DESC);

COMMIT;
