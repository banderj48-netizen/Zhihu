-- ============================================================
-- 知乎数字分身 PostgreSQL 初始化脚本
-- 使用方式：先连接到名为 zhihu 的数据库，再执行本文件。
-- 本脚本只负责建表、约束、索引和字段注释，不负责创建数据库。
-- 业务约束：一个用户只能拥有一个数字分身。
-- ============================================================

BEGIN;

-- UUID 默认值依赖以下扩展。
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ============================================================
-- 用户与数字分身
-- ============================================================

CREATE TABLE IF NOT EXISTS public.users (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    external_id varchar(128),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    deleted_at timestamptz,
    CONSTRAINT uq_users_external_id UNIQUE (external_id)
);

COMMENT ON TABLE public.users IS '系统用户表，数字分身的归属主体';
COMMENT ON COLUMN public.users.id IS '用户唯一标识';
COMMENT ON COLUMN public.users.external_id IS '外部系统中的用户标识，例如登录系统用户ID';
COMMENT ON COLUMN public.users.created_at IS '用户创建时间';
COMMENT ON COLUMN public.users.updated_at IS '用户最后更新时间';
COMMENT ON COLUMN public.users.deleted_at IS '软删除时间，未删除时为空';

CREATE TABLE IF NOT EXISTS public.user_avatars (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL,
    avatar_schema varchar(64) NOT NULL DEFAULT 'digital_twin_v1',
    display_name varchar(100),
    summary text,
    status varchar(32) NOT NULL DEFAULT 'building',
    current_version_id uuid,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    last_imported_at timestamptz,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT uq_user_avatars_user_id UNIQUE (user_id),
    CONSTRAINT ck_user_avatars_status CHECK (status IN ('building', 'ready', 'paused', 'archived')),
    CONSTRAINT fk_user_avatars_user FOREIGN KEY (user_id)
        REFERENCES public.users(id) ON DELETE CASCADE
);

COMMENT ON TABLE public.user_avatars IS '用户数字分身主表；每个用户最多一条记录';
COMMENT ON COLUMN public.user_avatars.id IS '数字分身唯一标识';
COMMENT ON COLUMN public.user_avatars.user_id IS '所属用户；唯一约束保证一人一个数字分身';
COMMENT ON COLUMN public.user_avatars.avatar_schema IS '画像结构版本，例如 digital_twin_v1';
COMMENT ON COLUMN public.user_avatars.display_name IS '数字分身展示名称';
COMMENT ON COLUMN public.user_avatars.summary IS '用户身份和特点的摘要';
COMMENT ON COLUMN public.user_avatars.status IS '数字分身状态：building构建中、ready可用、paused暂停、archived归档';
COMMENT ON COLUMN public.user_avatars.current_version_id IS '当前生效的画像版本';
COMMENT ON COLUMN public.user_avatars.last_imported_at IS '最后一次导入用户资料的时间';
COMMENT ON COLUMN public.user_avatars.metadata IS '不影响核心查询的扩展元数据';

-- ============================================================
-- 画像版本与稳定身份
-- ============================================================

CREATE TABLE IF NOT EXISTS public.avatar_versions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    avatar_id uuid NOT NULL,
    version_no integer NOT NULL,
    source_type varchar(32) NOT NULL DEFAULT 'llm_extract',
    base_version_id uuid,
    status varchar(32) NOT NULL DEFAULT 'draft',
    change_summary text,
    snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_by varchar(32) NOT NULL DEFAULT 'system',
    created_at timestamptz NOT NULL DEFAULT now(),
    activated_at timestamptz,
    CONSTRAINT uq_avatar_versions_no UNIQUE (avatar_id, version_no),
    CONSTRAINT ck_avatar_versions_source_type CHECK (source_type IN ('llm_extract', 'user_edit', 'system_merge')),
    CONSTRAINT ck_avatar_versions_status CHECK (status IN ('draft', 'active', 'superseded', 'rejected')),
    CONSTRAINT ck_avatar_versions_created_by CHECK (created_by IN ('system', 'user', 'admin')),
    CONSTRAINT fk_avatar_versions_avatar FOREIGN KEY (avatar_id)
        REFERENCES public.user_avatars(id) ON DELETE CASCADE,
    CONSTRAINT fk_avatar_versions_base FOREIGN KEY (base_version_id)
        REFERENCES public.avatar_versions(id) ON DELETE SET NULL
);

COMMENT ON TABLE public.avatar_versions IS '数字分身画像版本表，用于版本追踪、回滚和审计';
COMMENT ON COLUMN public.avatar_versions.id IS '画像版本唯一标识';
COMMENT ON COLUMN public.avatar_versions.avatar_id IS '所属数字分身';
COMMENT ON COLUMN public.avatar_versions.version_no IS '同一数字分身内递增的版本号';
COMMENT ON COLUMN public.avatar_versions.source_type IS '版本生成方式：LLM提炼、用户修改或系统合并';
COMMENT ON COLUMN public.avatar_versions.base_version_id IS '本版本基于的旧版本';
COMMENT ON COLUMN public.avatar_versions.status IS '版本状态：草稿、生效、已替换或拒绝';
COMMENT ON COLUMN public.avatar_versions.change_summary IS '本次版本的修改摘要';
COMMENT ON COLUMN public.avatar_versions.snapshot IS '该版本的完整画像快照，便于导出和回滚';
COMMENT ON COLUMN public.avatar_versions.created_by IS '版本创建者类型';
COMMENT ON COLUMN public.avatar_versions.activated_at IS '版本开始生效的时间';

CREATE UNIQUE INDEX IF NOT EXISTS uq_avatar_versions_active
    ON public.avatar_versions (avatar_id)
    WHERE status = 'active';

ALTER TABLE public.user_avatars
    DROP CONSTRAINT IF EXISTS fk_user_avatars_current_version;
ALTER TABLE public.user_avatars
    ADD CONSTRAINT fk_user_avatars_current_version
    FOREIGN KEY (current_version_id) REFERENCES public.avatar_versions(id) ON DELETE SET NULL;

CREATE TABLE IF NOT EXISTS public.avatar_identity (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    avatar_version_id uuid NOT NULL UNIQUE,
    display_name varchar(100),
    summary text,
    occupation varchar(200),
    location varchar(200),
    age smallint,
    privacy_level varchar(32) NOT NULL DEFAULT 'private',
    extra jsonb NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT ck_avatar_identity_privacy CHECK (privacy_level IN ('public', 'private', 'sensitive')),
    CONSTRAINT ck_avatar_identity_age CHECK (age IS NULL OR age BETWEEN 0 AND 200),
    CONSTRAINT fk_avatar_identity_version FOREIGN KEY (avatar_version_id)
        REFERENCES public.avatar_versions(id) ON DELETE CASCADE
);

COMMENT ON TABLE public.avatar_identity IS '数字分身的稳定身份信息';
COMMENT ON COLUMN public.avatar_identity.id IS '身份记录唯一标识';
COMMENT ON COLUMN public.avatar_identity.avatar_version_id IS '所属画像版本；每个版本最多一份身份信息';
COMMENT ON COLUMN public.avatar_identity.display_name IS '用户希望数字分身使用的称呼';
COMMENT ON COLUMN public.avatar_identity.summary IS '身份概括';
COMMENT ON COLUMN public.avatar_identity.occupation IS '职业或主要身份';
COMMENT ON COLUMN public.avatar_identity.location IS '所在地区；敏感信息需遵循隐私策略';
COMMENT ON COLUMN public.avatar_identity.age IS '年龄；无法确认时为空';
COMMENT ON COLUMN public.avatar_identity.privacy_level IS '身份信息隐私级别';
COMMENT ON COLUMN public.avatar_identity.extra IS '其他身份扩展字段';

-- ============================================================
-- 原始资料、记忆和证据
-- ============================================================

CREATE TABLE IF NOT EXISTS public.source_documents (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL,
    avatar_id uuid NOT NULL,
    platform varchar(32) NOT NULL,
    external_id varchar(200),
    document_type varchar(32) NOT NULL,
    title text,
    content text NOT NULL,
    source_url text,
    published_at timestamptz,
    content_hash varchar(128) NOT NULL,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    imported_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_source_documents_external UNIQUE (platform, external_id),
    CONSTRAINT fk_source_documents_user FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE,
    CONSTRAINT fk_source_documents_avatar FOREIGN KEY (avatar_id) REFERENCES public.user_avatars(id) ON DELETE CASCADE
);

COMMENT ON TABLE public.source_documents IS '用户原始资料，例如知乎回答、文章和评论';
COMMENT ON COLUMN public.source_documents.id IS '原始资料内部唯一标识';
COMMENT ON COLUMN public.source_documents.user_id IS '资料所属用户';
COMMENT ON COLUMN public.source_documents.avatar_id IS '资料归属的唯一数字分身';
COMMENT ON COLUMN public.source_documents.platform IS '资料来源平台，例如 zhihu';
COMMENT ON COLUMN public.source_documents.external_id IS '来源平台中的文档ID';
COMMENT ON COLUMN public.source_documents.document_type IS '文档类型：answer、article或comment';
COMMENT ON COLUMN public.source_documents.title IS '原始资料标题';
COMMENT ON COLUMN public.source_documents.content IS '原始正文内容';
COMMENT ON COLUMN public.source_documents.source_url IS '原始资料链接';
COMMENT ON COLUMN public.source_documents.published_at IS '原始资料发布时间';
COMMENT ON COLUMN public.source_documents.content_hash IS '正文哈希，用于去重和变更检测';
COMMENT ON COLUMN public.source_documents.metadata IS '平台相关扩展信息';
COMMENT ON COLUMN public.source_documents.imported_at IS '导入系统的时间';

CREATE TABLE IF NOT EXISTS public.avatar_memories (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    avatar_id uuid NOT NULL,
    version_id uuid,
    memory_type varchar(32) NOT NULL,
    topic varchar(200),
    content text NOT NULL,
    structured_data jsonb NOT NULL DEFAULT '{}'::jsonb,
    level varchar(32),
    score numeric(5,4),
    confidence numeric(5,4),
    status varchar(32) NOT NULL DEFAULT 'unconfirmed',
    privacy varchar(32) NOT NULL DEFAULT 'private',
    valid_from timestamptz,
    valid_until timestamptz,
    evidence_count integer NOT NULL DEFAULT 0,
    embedding jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_avatar_memories_score CHECK (score IS NULL OR score BETWEEN 0 AND 1),
    CONSTRAINT ck_avatar_memories_confidence CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1),
    CONSTRAINT ck_avatar_memories_status CHECK (status IN ('confirmed', 'unconfirmed', 'rejected', 'expired')),
    CONSTRAINT ck_avatar_memories_privacy CHECK (privacy IN ('public', 'private', 'sensitive')),
    CONSTRAINT ck_avatar_memories_valid_time CHECK (valid_until IS NULL OR valid_from IS NULL OR valid_until >= valid_from),
    CONSTRAINT fk_avatar_memories_avatar FOREIGN KEY (avatar_id) REFERENCES public.user_avatars(id) ON DELETE CASCADE,
    CONSTRAINT fk_avatar_memories_version FOREIGN KEY (version_id) REFERENCES public.avatar_versions(id) ON DELETE SET NULL
);

COMMENT ON TABLE public.avatar_memories IS '数字分身可检索的事实、经历、专长、兴趣、观点和行为记忆';
COMMENT ON COLUMN public.avatar_memories.id IS '记忆唯一标识';
COMMENT ON COLUMN public.avatar_memories.avatar_id IS '所属唯一数字分身';
COMMENT ON COLUMN public.avatar_memories.version_id IS '该记忆进入画像的版本';
COMMENT ON COLUMN public.avatar_memories.memory_type IS '记忆类型：fact、experience、expertise、interest、opinion或behavior';
COMMENT ON COLUMN public.avatar_memories.topic IS '记忆主题，例如 Rust、远程办公';
COMMENT ON COLUMN public.avatar_memories.content IS '记忆的自然语言内容';
COMMENT ON COLUMN public.avatar_memories.structured_data IS '条件、论据、例外等结构化内容';
COMMENT ON COLUMN public.avatar_memories.level IS '专长或兴趣等级';
COMMENT ON COLUMN public.avatar_memories.score IS '模型对相关性或强度的评分';
COMMENT ON COLUMN public.avatar_memories.confidence IS '模型对该记忆真实性的置信度';
COMMENT ON COLUMN public.avatar_memories.status IS '记忆状态：已确认、未确认、已拒绝或已过期';
COMMENT ON COLUMN public.avatar_memories.privacy IS '记忆隐私级别';
COMMENT ON COLUMN public.avatar_memories.valid_from IS '记忆开始生效时间';
COMMENT ON COLUMN public.avatar_memories.valid_until IS '记忆失效时间';
COMMENT ON COLUMN public.avatar_memories.evidence_count IS '支持该记忆的证据数量';
COMMENT ON COLUMN public.avatar_memories.embedding IS '可选的记忆向量；未安装pgvector时以JSON数组保存';

CREATE TABLE IF NOT EXISTS public.memory_evidence (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    memory_id uuid NOT NULL,
    source_document_id uuid NOT NULL,
    quote text NOT NULL,
    evidence_type varchar(32) NOT NULL DEFAULT 'user_original',
    relevance_score numeric(5,4),
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_memory_evidence_relation UNIQUE (memory_id, source_document_id, quote),
    CONSTRAINT ck_memory_evidence_type CHECK (evidence_type IN ('user_original', 'inference', 'correction')),
    CONSTRAINT ck_memory_evidence_relevance CHECK (relevance_score IS NULL OR relevance_score BETWEEN 0 AND 1),
    CONSTRAINT fk_memory_evidence_memory FOREIGN KEY (memory_id) REFERENCES public.avatar_memories(id) ON DELETE CASCADE,
    CONSTRAINT fk_memory_evidence_document FOREIGN KEY (source_document_id) REFERENCES public.source_documents(id) ON DELETE CASCADE
);

COMMENT ON TABLE public.memory_evidence IS '画像记忆与原始资料之间的证据关联';
COMMENT ON COLUMN public.memory_evidence.id IS '证据关联唯一标识';
COMMENT ON COLUMN public.memory_evidence.memory_id IS '被支持的记忆';
COMMENT ON COLUMN public.memory_evidence.source_document_id IS '提供证据的原始资料';
COMMENT ON COLUMN public.memory_evidence.quote IS '原始资料中的引用片段';
COMMENT ON COLUMN public.memory_evidence.evidence_type IS '证据类型：用户原文、模型推断或用户纠正';
COMMENT ON COLUMN public.memory_evidence.relevance_score IS '证据与记忆的相关性评分';

-- ============================================================
-- 性格、表达风格和策略
-- ============================================================

CREATE TABLE IF NOT EXISTS public.avatar_personality (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    avatar_version_id uuid NOT NULL UNIQUE,
    model_name varchar(64) NOT NULL,
    scores jsonb NOT NULL DEFAULT '{}'::jsonb,
    style_tags jsonb NOT NULL DEFAULT '[]'::jsonb,
    confidence numeric(5,4),
    inference_source varchar(64) NOT NULL DEFAULT 'inferred_from_user_data',
    status varchar(32) NOT NULL DEFAULT 'unconfirmed',
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_avatar_personality_confidence CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1),
    CONSTRAINT ck_avatar_personality_status CHECK (status IN ('confirmed', 'unconfirmed', 'rejected')),
    CONSTRAINT fk_avatar_personality_version FOREIGN KEY (avatar_version_id) REFERENCES public.avatar_versions(id) ON DELETE CASCADE
);

COMMENT ON TABLE public.avatar_personality IS '数字分身的性格模型和推断结果';
COMMENT ON COLUMN public.avatar_personality.id IS '性格记录唯一标识';
COMMENT ON COLUMN public.avatar_personality.avatar_version_id IS '所属画像版本，每个版本最多一份性格信息';
COMMENT ON COLUMN public.avatar_personality.model_name IS '性格模型名称，例如 big_five';
COMMENT ON COLUMN public.avatar_personality.scores IS '性格模型各维度得分';
COMMENT ON COLUMN public.avatar_personality.style_tags IS '性格风格标签，例如直接、理性、克制';
COMMENT ON COLUMN public.avatar_personality.confidence IS '性格推断置信度';
COMMENT ON COLUMN public.avatar_personality.inference_source IS '性格结果的推断来源';
COMMENT ON COLUMN public.avatar_personality.status IS '性格结果是否已被确认';

CREATE TABLE IF NOT EXISTS public.avatar_styles (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    avatar_version_id uuid NOT NULL UNIQUE,
    tone jsonb NOT NULL DEFAULT '[]'::jsonb,
    structure_rules jsonb NOT NULL DEFAULT '[]'::jsonb,
    verbosity varchar(32) NOT NULL DEFAULT 'medium',
    technical_density varchar(32),
    sentence_style text,
    uncertainty_style text,
    preferred_registers jsonb NOT NULL DEFAULT '[]'::jsonb,
    avoid_rules jsonb NOT NULL DEFAULT '[]'::jsonb,
    extra jsonb NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT fk_avatar_styles_version FOREIGN KEY (avatar_version_id) REFERENCES public.avatar_versions(id) ON DELETE CASCADE
);

COMMENT ON TABLE public.avatar_styles IS '数字分身的表达风格规则';
COMMENT ON COLUMN public.avatar_styles.id IS '表达风格记录唯一标识';
COMMENT ON COLUMN public.avatar_styles.avatar_version_id IS '所属画像版本，每个版本最多一份风格配置';
COMMENT ON COLUMN public.avatar_styles.tone IS '语气标签，例如直接、克制、理性';
COMMENT ON COLUMN public.avatar_styles.structure_rules IS '回答结构规则，例如先结论再条件最后举例';
COMMENT ON COLUMN public.avatar_styles.verbosity IS '表达详细程度';
COMMENT ON COLUMN public.avatar_styles.technical_density IS '技术内容密度';
COMMENT ON COLUMN public.avatar_styles.sentence_style IS '句式特征';
COMMENT ON COLUMN public.avatar_styles.uncertainty_style IS '表达不确定性的方式';
COMMENT ON COLUMN public.avatar_styles.preferred_registers IS '适用表达场景，例如 chat、answer';
COMMENT ON COLUMN public.avatar_styles.avoid_rules IS '应避免的表达方式';
COMMENT ON COLUMN public.avatar_styles.extra IS '表达风格扩展配置';

CREATE TABLE IF NOT EXISTS public.avatar_style_examples (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    avatar_id uuid NOT NULL,
    register varchar(32) NOT NULL,
    text text NOT NULL,
    source_document_id uuid,
    embedding jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_avatar_style_examples_avatar FOREIGN KEY (avatar_id) REFERENCES public.user_avatars(id) ON DELETE CASCADE,
    CONSTRAINT fk_avatar_style_examples_document FOREIGN KEY (source_document_id) REFERENCES public.source_documents(id) ON DELETE SET NULL
);

COMMENT ON TABLE public.avatar_style_examples IS '用户真实表达样例，用于模仿语气和句式';
COMMENT ON COLUMN public.avatar_style_examples.id IS '表达样例唯一标识';
COMMENT ON COLUMN public.avatar_style_examples.avatar_id IS '所属唯一数字分身';
COMMENT ON COLUMN public.avatar_style_examples.register IS '表达场景，例如 chat 或 answer';
COMMENT ON COLUMN public.avatar_style_examples.text IS '用户真实写过的文本';
COMMENT ON COLUMN public.avatar_style_examples.source_document_id IS '样例来源原始资料';
COMMENT ON COLUMN public.avatar_style_examples.embedding IS '可选的表达样例向量；未安装pgvector时以JSON数组保存';

CREATE TABLE IF NOT EXISTS public.avatar_memory_rules (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    avatar_id uuid NOT NULL UNIQUE,
    top_k integer NOT NULL DEFAULT 8,
    use_vector_search boolean NOT NULL DEFAULT true,
    use_keyword_search boolean NOT NULL DEFAULT true,
    prefer_confirmed boolean NOT NULL DEFAULT true,
    prefer_recent_opinions boolean NOT NULL DEFAULT true,
    confidence_policy jsonb NOT NULL DEFAULT '{}'::jsonb,
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_avatar_memory_rules_top_k CHECK (top_k BETWEEN 1 AND 100),
    CONSTRAINT fk_avatar_memory_rules_avatar FOREIGN KEY (avatar_id) REFERENCES public.user_avatars(id) ON DELETE CASCADE
);

COMMENT ON TABLE public.avatar_memory_rules IS '数字分身记忆检索和排序规则；每个分身一份';
COMMENT ON COLUMN public.avatar_memory_rules.id IS '检索规则唯一标识';
COMMENT ON COLUMN public.avatar_memory_rules.avatar_id IS '所属唯一数字分身';
COMMENT ON COLUMN public.avatar_memory_rules.top_k IS '每次最多召回的记忆数量';
COMMENT ON COLUMN public.avatar_memory_rules.use_vector_search IS '是否启用向量检索';
COMMENT ON COLUMN public.avatar_memory_rules.use_keyword_search IS '是否启用关键词检索';
COMMENT ON COLUMN public.avatar_memory_rules.prefer_confirmed IS '是否优先召回已确认记忆';
COMMENT ON COLUMN public.avatar_memory_rules.prefer_recent_opinions IS '是否优先召回较新的观点';
COMMENT ON COLUMN public.avatar_memory_rules.confidence_policy IS '不同来源和推断级别的置信度规则';

CREATE TABLE IF NOT EXISTS public.avatar_policies (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    avatar_id uuid NOT NULL UNIQUE,
    can_use_unconfirmed_memory boolean NOT NULL DEFAULT true,
    can_present_unconfirmed_as_fact boolean NOT NULL DEFAULT false,
    can_invent_user_experience boolean NOT NULL DEFAULT false,
    can_invent_user_opinion boolean NOT NULL DEFAULT false,
    must_show_uncertainty boolean NOT NULL DEFAULT true,
    must_keep_citations boolean NOT NULL DEFAULT true,
    sensitive_attributes_policy varchar(32) NOT NULL DEFAULT 'do_not_infer',
    external_action_requires_confirmation boolean NOT NULL DEFAULT true,
    custom_rules jsonb NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT fk_avatar_policies_avatar FOREIGN KEY (avatar_id) REFERENCES public.user_avatars(id) ON DELETE CASCADE
);

COMMENT ON TABLE public.avatar_policies IS '数字分身的安全、隐私和外部行为策略；每个分身一份';
COMMENT ON COLUMN public.avatar_policies.id IS '策略记录唯一标识';
COMMENT ON COLUMN public.avatar_policies.avatar_id IS '所属唯一数字分身';
COMMENT ON COLUMN public.avatar_policies.can_use_unconfirmed_memory IS '是否允许使用未确认记忆';
COMMENT ON COLUMN public.avatar_policies.can_present_unconfirmed_as_fact IS '是否允许把未确认推断直接表述为事实';
COMMENT ON COLUMN public.avatar_policies.can_invent_user_experience IS '是否允许虚构用户经历，默认禁止';
COMMENT ON COLUMN public.avatar_policies.can_invent_user_opinion IS '是否允许虚构用户观点，默认禁止';
COMMENT ON COLUMN public.avatar_policies.must_show_uncertainty IS '使用不确定记忆时是否必须说明不确定性';
COMMENT ON COLUMN public.avatar_policies.must_keep_citations IS '回答中是否必须保留证据引用';
COMMENT ON COLUMN public.avatar_policies.sensitive_attributes_policy IS '敏感属性处理策略，默认不推断';
COMMENT ON COLUMN public.avatar_policies.external_action_requires_confirmation IS '执行外部操作前是否必须获得确认';
COMMENT ON COLUMN public.avatar_policies.custom_rules IS '业务自定义策略';

-- ============================================================
-- 成长评估与审计
-- ============================================================

CREATE TABLE IF NOT EXISTS public.avatar_growth_evaluations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    avatar_id uuid NOT NULL,
    version_id uuid,
    round_no integer NOT NULL DEFAULT 0,
    match_count integer NOT NULL DEFAULT 0,
    accuracy numeric(5,4),
    corrections_count integer NOT NULL DEFAULT 0,
    metric_detail jsonb NOT NULL DEFAULT '{}'::jsonb,
    evaluated_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_avatar_growth_accuracy CHECK (accuracy IS NULL OR accuracy BETWEEN 0 AND 1),
    CONSTRAINT fk_avatar_growth_avatar FOREIGN KEY (avatar_id) REFERENCES public.user_avatars(id) ON DELETE CASCADE,
    CONSTRAINT fk_avatar_growth_version FOREIGN KEY (version_id) REFERENCES public.avatar_versions(id) ON DELETE SET NULL
);

COMMENT ON TABLE public.avatar_growth_evaluations IS '数字分身准确率、匹配度和纠正次数的评估记录';
COMMENT ON COLUMN public.avatar_growth_evaluations.id IS '评估记录唯一标识';
COMMENT ON COLUMN public.avatar_growth_evaluations.avatar_id IS '所属唯一数字分身';
COMMENT ON COLUMN public.avatar_growth_evaluations.version_id IS '被评估的画像版本';
COMMENT ON COLUMN public.avatar_growth_evaluations.round_no IS '成长评估轮次';
COMMENT ON COLUMN public.avatar_growth_evaluations.match_count IS '与用户真实回答或行为匹配的次数';
COMMENT ON COLUMN public.avatar_growth_evaluations.accuracy IS '本轮画像准确率';
COMMENT ON COLUMN public.avatar_growth_evaluations.corrections_count IS '用户纠正画像的次数';
COMMENT ON COLUMN public.avatar_growth_evaluations.metric_detail IS '按领域、场景和记忆类型拆分的指标';
COMMENT ON COLUMN public.avatar_growth_evaluations.evaluated_at IS '评估完成时间';

CREATE TABLE IF NOT EXISTS public.avatar_change_logs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    avatar_id uuid NOT NULL,
    version_id uuid,
    operator_type varchar(32) NOT NULL,
    operation varchar(32) NOT NULL,
    target_type varchar(32) NOT NULL,
    target_id uuid,
    before_data jsonb,
    after_data jsonb,
    reason text,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_avatar_change_logs_operator CHECK (operator_type IN ('user', 'system', 'admin')),
    CONSTRAINT fk_avatar_change_logs_avatar FOREIGN KEY (avatar_id) REFERENCES public.user_avatars(id) ON DELETE CASCADE,
    CONSTRAINT fk_avatar_change_logs_version FOREIGN KEY (version_id) REFERENCES public.avatar_versions(id) ON DELETE SET NULL
);

COMMENT ON TABLE public.avatar_change_logs IS '数字分身修改、确认、拒绝和过期操作的审计日志';
COMMENT ON COLUMN public.avatar_change_logs.id IS '审计日志唯一标识';
COMMENT ON COLUMN public.avatar_change_logs.avatar_id IS '所属唯一数字分身';
COMMENT ON COLUMN public.avatar_change_logs.version_id IS '受影响的画像版本';
COMMENT ON COLUMN public.avatar_change_logs.operator_type IS '操作发起者：用户、系统或管理员';
COMMENT ON COLUMN public.avatar_change_logs.operation IS '操作类型：创建、更新、确认、拒绝或过期';
COMMENT ON COLUMN public.avatar_change_logs.target_type IS '被修改对象类型';
COMMENT ON COLUMN public.avatar_change_logs.target_id IS '被修改对象ID';
COMMENT ON COLUMN public.avatar_change_logs.before_data IS '修改前数据';
COMMENT ON COLUMN public.avatar_change_logs.after_data IS '修改后数据';
COMMENT ON COLUMN public.avatar_change_logs.reason IS '修改原因';

-- ============================================================
-- 索引
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_avatar_versions_avatar_status
    ON public.avatar_versions (avatar_id, status);
CREATE INDEX IF NOT EXISTS idx_source_documents_avatar_type
    ON public.source_documents (avatar_id, document_type);
CREATE INDEX IF NOT EXISTS idx_avatar_memories_avatar_type_status
    ON public.avatar_memories (avatar_id, memory_type, status);
CREATE INDEX IF NOT EXISTS idx_avatar_memories_topic
    ON public.avatar_memories (topic);
CREATE INDEX IF NOT EXISTS idx_memory_evidence_memory
    ON public.memory_evidence (memory_id);
CREATE INDEX IF NOT EXISTS idx_memory_evidence_document
    ON public.memory_evidence (source_document_id);
CREATE INDEX IF NOT EXISTS idx_style_examples_avatar_register
    ON public.avatar_style_examples (avatar_id, register);
CREATE INDEX IF NOT EXISTS idx_growth_evaluations_avatar_time
    ON public.avatar_growth_evaluations (avatar_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_change_logs_avatar_time
    ON public.avatar_change_logs (avatar_id, created_at DESC);

-- 如果后续安装 pgvector，可将上述 embedding 字段迁移为 vector(1536)，
-- 再按实际模型维度创建 HNSW 索引；当前脚本不强制依赖该扩展。

COMMIT;
