-- ============================================================
-- 性格测评 / 领域选择模块兼容表（TEXT-ID 旧模块 × UUID 正式 schema 共存）
-- 使用方式：先连接 zhihu 数据库，并先执行完 8 个 postgresql_*.sql 正式脚本
-- （initialize_formal），再执行本文件。
-- 背景：agent/personality 与 agent/domains 模块仍使用 TEXT 主键的
-- avatars / personality_assessments / avatar_domain_selections 三张表，
-- 而正式 schema 的 public.users 已是 UUID 主键 + external_id 唯一约束，
-- 因此这里的 avatars.user_id 保留 TEXT 且不建指向 users 的外键，
-- 用户归属关系由应用层（_ensure_avatar/_avatar 先 upsert users）维护。
-- ============================================================

BEGIN;

-- 测评归属主体：一人一分身（应用层按 user_id 取第一条未删除记录）
CREATE TABLE IF NOT EXISTS public.avatars (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    name TEXT,
    status TEXT NOT NULL DEFAULT 'not_started',
    current_version INTEGER,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    deleted_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_avatars_user ON public.avatars(user_id);

COMMENT ON TABLE public.avatars IS '性格测评与领域选择模块的轻量分身记录（兼容表，正式分身见 user_avatars）';
COMMENT ON COLUMN public.avatars.user_id IS '用户标识：UUID 字符串或登录系统 external_id';

-- 性格测评结果（含迁移 002 的结果快照与幂等键）
CREATE TABLE IF NOT EXISTS public.personality_assessments (
    id TEXT PRIMARY KEY,
    avatar_id TEXT NOT NULL REFERENCES public.avatars(id) ON DELETE CASCADE,
    instrument_version TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'incomplete',
    raw_answers_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    scores_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    confidence REAL,
    confidence_interval_json JSONB,
    validity_json JSONB,
    source_mix_json JSONB,
    skipped BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    result_json JSONB,
    request_key TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_personality_assessment_request
    ON public.personality_assessments(avatar_id, request_key)
    WHERE request_key IS NOT NULL;

COMMENT ON TABLE public.personality_assessments IS '大五性格测评结果（50 题 IPIP），request_key 保证提交幂等';

-- 兴趣与自评擅长领域选择（迁移 003，软删除 + revision 乐观锁）
CREATE TABLE IF NOT EXISTS public.avatar_domain_selections (
    id TEXT PRIMARY KEY,
    avatar_id TEXT NOT NULL REFERENCES public.avatars(id) ON DELETE CASCADE,
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
CREATE INDEX IF NOT EXISTS idx_domain_selection_avatar ON public.avatar_domain_selections(avatar_id, selection_type, deleted_at);
CREATE INDEX IF NOT EXISTS idx_domain_selection_domain ON public.avatar_domain_selections(domain_id);

COMMENT ON TABLE public.avatar_domain_selections IS '用户选择的兴趣与自评擅长领域，interest_level 0-3，proficiency 为自评熟练度';

COMMIT;
