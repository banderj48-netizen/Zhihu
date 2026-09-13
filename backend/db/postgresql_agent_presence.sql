-- 看山场景在场状态与用户日程
-- 依赖：postgresql_zhihu_schema.sql、postgresql_agent_dialogue.sql
BEGIN;

CREATE TABLE IF NOT EXISTS public.agent_scene_presence (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    avatar_id uuid NOT NULL REFERENCES public.user_avatars(id) ON DELETE CASCADE,
    scene_id varchar(64) NOT NULL,
    status varchar(16) NOT NULL DEFAULT 'idle',
    current_dialogue_run_id uuid REFERENCES public.agent_dialogue_runs(id) ON DELETE SET NULL,
    display_summary jsonb NOT NULL DEFAULT '{}'::jsonb,
    last_seen_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_agent_scene_presence_avatar_scene UNIQUE (avatar_id, scene_id),
    CONSTRAINT ck_agent_scene_presence_status CHECK (status IN ('idle', 'busy', 'offline'))
);

COMMENT ON TABLE public.agent_scene_presence IS '数字分身在各个聊天场景中的在线与占用状态';
COMMENT ON COLUMN public.agent_scene_presence.avatar_id IS '在场的数字分身';
COMMENT ON COLUMN public.agent_scene_presence.scene_id IS '场景唯一标识';
COMMENT ON COLUMN public.agent_scene_presence.status IS '在场状态：idle空闲、busy聊天中、offline离线';
COMMENT ON COLUMN public.agent_scene_presence.current_dialogue_run_id IS '当前占用该看山的对话运行';
COMMENT ON COLUMN public.agent_scene_presence.display_summary IS '供场景列表展示的最小公开画像摘要';

CREATE INDEX IF NOT EXISTS idx_agent_scene_presence_scene_status
    ON public.agent_scene_presence(scene_id, status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_scene_presence_avatar
    ON public.agent_scene_presence(avatar_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS public.agent_world_days (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    day_no integer NOT NULL DEFAULT 1,
    selected_scene_id varchar(64),
    last_dialogue_run_id uuid REFERENCES public.agent_dialogue_runs(id) ON DELETE SET NULL,
    day_status varchar(16) NOT NULL DEFAULT 'selecting',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_agent_world_days_user UNIQUE (user_id),
    CONSTRAINT ck_agent_world_days_status CHECK (day_status IN ('selecting', 'running', 'completed')),
    CONSTRAINT ck_agent_world_days_number CHECK (day_no >= 1)
);

COMMENT ON TABLE public.agent_world_days IS '用户看山每日场景与对话进度';
COMMENT ON COLUMN public.agent_world_days.user_id IS '用户唯一标识';
COMMENT ON COLUMN public.agent_world_days.day_no IS '当前体验天数，从1开始';
COMMENT ON COLUMN public.agent_world_days.selected_scene_id IS '当天选择的场景';
COMMENT ON COLUMN public.agent_world_days.last_dialogue_run_id IS '上一轮双 Agent 对话';
COMMENT ON COLUMN public.agent_world_days.day_status IS '日状态：选场景、对话中或已完成';

COMMIT;
