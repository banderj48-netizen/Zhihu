-- ============================================================
-- 知乎数字分身聊天记录 PostgreSQL 建表脚本
-- 使用方式：连接到 zhihu 数据库后执行本文件。
-- 前置条件：已执行 postgresql_zhihu_schema.sql，且存在 public.user_avatars 表。
-- 设计目标：保存分身之间真实、可排序、可追溯的聊天记录。
-- ============================================================

BEGIN;

-- ============================================================
-- 聊天会话
-- ============================================================

CREATE TABLE IF NOT EXISTS public.chat_conversations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_type varchar(32) NOT NULL DEFAULT 'direct',
    title varchar(200),
    status varchar(32) NOT NULL DEFAULT 'active',
    started_at timestamptz NOT NULL DEFAULT now(),
    ended_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT ck_chat_conversations_type CHECK (conversation_type IN ('direct', 'group', 'system')),
    CONSTRAINT ck_chat_conversations_status CHECK (status IN ('active', 'ended', 'archived', 'deleted')),
    CONSTRAINT ck_chat_conversations_time CHECK (ended_at IS NULL OR ended_at >= started_at)
);

COMMENT ON TABLE public.chat_conversations IS '数字分身聊天会话表，保存一次对话的整体信息';
COMMENT ON COLUMN public.chat_conversations.id IS '聊天会话唯一标识';
COMMENT ON COLUMN public.chat_conversations.conversation_type IS '会话类型：direct一对一、group群聊、system系统会话';
COMMENT ON COLUMN public.chat_conversations.title IS '会话标题，可由系统生成或用户设置';
COMMENT ON COLUMN public.chat_conversations.status IS '会话状态：进行中、已结束、已归档或已删除';
COMMENT ON COLUMN public.chat_conversations.started_at IS '会话开始时间';
COMMENT ON COLUMN public.chat_conversations.ended_at IS '会话结束时间，未结束时为空';
COMMENT ON COLUMN public.chat_conversations.created_at IS '会话记录创建时间';
COMMENT ON COLUMN public.chat_conversations.updated_at IS '会话最后更新时间';
COMMENT ON COLUMN public.chat_conversations.metadata IS '会话级扩展信息，例如生成参数、业务来源和标签';

-- ============================================================
-- 会话参与者
-- ============================================================

CREATE TABLE IF NOT EXISTS public.chat_participants (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id uuid NOT NULL,
    avatar_id uuid,
    participant_type varchar(32) NOT NULL DEFAULT 'avatar',
    display_name varchar(100),
    role varchar(32) NOT NULL DEFAULT 'member',
    joined_at timestamptz NOT NULL DEFAULT now(),
    left_at timestamptz,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT ck_chat_participants_type CHECK (participant_type IN ('avatar', 'user', 'system')),
    CONSTRAINT ck_chat_participants_role CHECK (role IN ('member', 'moderator', 'system')),
    CONSTRAINT ck_chat_participants_time CHECK (left_at IS NULL OR left_at >= joined_at),
    CONSTRAINT ck_chat_participants_avatar CHECK (
        (participant_type = 'avatar' AND avatar_id IS NOT NULL)
        OR (participant_type IN ('user', 'system') AND avatar_id IS NULL)
    ),
    CONSTRAINT uq_chat_participants_avatar UNIQUE (conversation_id, avatar_id),
    CONSTRAINT uq_chat_participants_id_conversation UNIQUE (id, conversation_id),
    CONSTRAINT fk_chat_participants_conversation FOREIGN KEY (conversation_id)
        REFERENCES public.chat_conversations(id) ON DELETE CASCADE,
    CONSTRAINT fk_chat_participants_avatar FOREIGN KEY (avatar_id)
        REFERENCES public.user_avatars(id) ON DELETE RESTRICT
);

COMMENT ON TABLE public.chat_participants IS '聊天会话参与者表，记录参与对话的数字分身及其身份快照';
COMMENT ON COLUMN public.chat_participants.id IS '参与者记录唯一标识，消息表通过此字段识别发送者';
COMMENT ON COLUMN public.chat_participants.conversation_id IS '所属聊天会话';
COMMENT ON COLUMN public.chat_participants.avatar_id IS '参与聊天的数字分身；分身参与者必填';
COMMENT ON COLUMN public.chat_participants.participant_type IS '参与者类型：avatar数字分身、user用户、system系统';
COMMENT ON COLUMN public.chat_participants.display_name IS '参与者在本次会话中的名称快照，避免名称修改影响历史记录展示';
COMMENT ON COLUMN public.chat_participants.role IS '参与者角色：普通成员、主持人或系统';
COMMENT ON COLUMN public.chat_participants.joined_at IS '参与者加入会话时间';
COMMENT ON COLUMN public.chat_participants.left_at IS '参与者离开会话时间';
COMMENT ON COLUMN public.chat_participants.metadata IS '参与者级扩展信息，例如模型、版本和客户端信息';

-- ============================================================
-- 真实聊天消息
-- ============================================================

CREATE TABLE IF NOT EXISTS public.chat_messages (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id uuid NOT NULL,
    participant_id uuid NOT NULL,
    sequence_no bigint NOT NULL,
    client_message_id varchar(128),
    message_type varchar(32) NOT NULL DEFAULT 'text',
    content text NOT NULL,
    content_format varchar(32) NOT NULL DEFAULT 'plain_text',
    reply_to_message_id uuid,
    sent_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now(),
    edited_at timestamptz,
    deleted_at timestamptz,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT uq_chat_messages_sequence UNIQUE (conversation_id, sequence_no),
    CONSTRAINT uq_chat_messages_client_id UNIQUE (conversation_id, client_message_id),
    CONSTRAINT ck_chat_messages_type CHECK (message_type IN ('text', 'image', 'file', 'audio', 'video', 'event', 'system')),
    CONSTRAINT ck_chat_messages_format CHECK (content_format IN ('plain_text', 'markdown', 'json')),
    CONSTRAINT fk_chat_messages_conversation FOREIGN KEY (conversation_id)
        REFERENCES public.chat_conversations(id) ON DELETE CASCADE,
    -- 复合外键保证发送者确实属于当前消息所在的会话。
    CONSTRAINT fk_chat_messages_participant FOREIGN KEY (participant_id, conversation_id)
        REFERENCES public.chat_participants(id, conversation_id) ON DELETE RESTRICT,
    CONSTRAINT fk_chat_messages_reply FOREIGN KEY (reply_to_message_id)
        REFERENCES public.chat_messages(id) ON DELETE SET NULL
);

COMMENT ON TABLE public.chat_messages IS '真实聊天消息表，每一行代表一条不可混淆的历史消息';
COMMENT ON COLUMN public.chat_messages.id IS '消息唯一标识';
COMMENT ON COLUMN public.chat_messages.conversation_id IS '所属聊天会话';
COMMENT ON COLUMN public.chat_messages.participant_id IS '发送消息的会话参与者';
COMMENT ON COLUMN public.chat_messages.sequence_no IS '会话内严格递增的消息序号，用于稳定排序';
COMMENT ON COLUMN public.chat_messages.client_message_id IS '客户端或上游系统消息ID，用于幂等去重';
COMMENT ON COLUMN public.chat_messages.message_type IS '消息类型：文本、图片、文件、音频、视频、事件或系统消息';
COMMENT ON COLUMN public.chat_messages.content IS '消息真实内容；文本消息直接保存原文，其他类型可保存JSON描述';
COMMENT ON COLUMN public.chat_messages.content_format IS '内容格式：纯文本、Markdown或JSON';
COMMENT ON COLUMN public.chat_messages.reply_to_message_id IS '被回复的消息ID，用于建立引用关系';
COMMENT ON COLUMN public.chat_messages.sent_at IS '消息实际发送时间，来自客户端或消息服务';
COMMENT ON COLUMN public.chat_messages.created_at IS '消息写入数据库时间';
COMMENT ON COLUMN public.chat_messages.edited_at IS '消息最后编辑时间，未编辑时为空';
COMMENT ON COLUMN public.chat_messages.deleted_at IS '消息软删除时间，保留记录但不再对普通用户展示';
COMMENT ON COLUMN public.chat_messages.metadata IS '消息扩展信息，例如模型、提示词版本、token统计和原始请求ID';

-- ============================================================
-- 索引：按会话拉取历史、按时间查询和审计消息
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_chat_conversations_status_time
    ON public.chat_conversations (status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_chat_participants_conversation
    ON public.chat_participants (conversation_id, joined_at);
CREATE INDEX IF NOT EXISTS idx_chat_participants_avatar
    ON public.chat_participants (avatar_id);
CREATE INDEX IF NOT EXISTS idx_chat_messages_conversation_sequence
    ON public.chat_messages (conversation_id, sequence_no);
CREATE INDEX IF NOT EXISTS idx_chat_messages_conversation_sent_at
    ON public.chat_messages (conversation_id, sent_at);
CREATE INDEX IF NOT EXISTS idx_chat_messages_participant_time
    ON public.chat_messages (participant_id, sent_at DESC);
CREATE INDEX IF NOT EXISTS idx_chat_messages_reply
    ON public.chat_messages (reply_to_message_id);
CREATE INDEX IF NOT EXISTS idx_chat_messages_active
    ON public.chat_messages (conversation_id, sent_at)
    WHERE deleted_at IS NULL;

COMMIT;
