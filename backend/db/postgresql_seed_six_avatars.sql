-- ============================================================
-- 为指定账号生成一个主数字分身和五个相似但不相同的测试分身
-- 使用方式：连接 zhihu 数据库后执行：
--   psql "$DATABASE_URL" -v target_user_key="你的用户ID或external_id" \
--     -f backend/db/postgresql_seed_six_avatars.sql
--
-- 重要约束：user_avatars.user_id 有唯一约束，一个用户只能拥有一个数字分身。
-- 因此五个相似分身使用五个明确标记的合成测试用户归属，不会破坏真实账号的一人一分身约束。
-- 本脚本只写入 PostgreSQL，不写入 Chroma；向量同步由既有 outbox 流程处理。
-- ============================================================

\if :{?target_user_key}
\else
\set target_user_key 'local-demo-user'
\endif

BEGIN;

CREATE TEMP TABLE _seed_avatar_map (
    label text PRIMARY KEY,
    user_id uuid NOT NULL,
    avatar_id uuid NOT NULL
) ON COMMIT DROP;

-- 解析本人账号：既支持 users.id（UUID），也支持 users.external_id。
DO $body$
DECLARE
    v_key text := :'target_user_key';
    v_user_id uuid;
BEGIN
    SELECT id INTO v_user_id
      FROM public.users
     WHERE id::text = v_key OR external_id = v_key
     ORDER BY created_at
     LIMIT 1;

    IF v_user_id IS NULL THEN
        IF v_key ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$' THEN
            INSERT INTO public.users(id) VALUES (v_key::uuid) RETURNING id INTO v_user_id;
        ELSE
            INSERT INTO public.users(external_id) VALUES (v_key)
            ON CONFLICT (external_id) DO UPDATE SET updated_at = now()
            RETURNING id INTO v_user_id;
        END IF;
    END IF;

    -- 用户解析结果通过后续 user_avatars 查询使用；此处不提前写入临时映射，
    -- 避免真实账号尚未建分身时出现空 avatar_id。
END;
$body$;

-- 五个合成用户仅用于相似分身样本，external_id 带 seed 前缀，便于识别和清理。
INSERT INTO public.users(external_id)
SELECT 'seed-similar-avatar-' || n
  FROM generate_series(1, 5) AS n
ON CONFLICT (external_id) DO UPDATE SET updated_at = now();

-- 为本人和五个合成用户各创建一条分身；已存在记录则保持幂等，不重复创建。
INSERT INTO public.user_avatars(user_id, display_name, summary, status, metadata)
SELECT u.id,
       CASE WHEN s.n = 0 THEN '我的看山' ELSE '相似样本看山 ' || s.n END,
       CASE WHEN s.n = 0 THEN '本人账号的数字分身' ELSE '与本人画像相近但参数不同的测试分身样本 ' || s.n END,
       'ready',
       jsonb_build_object('seed_script', 'postgresql_seed_six_avatars.sql', 'synthetic', s.n > 0, 'variant', s.n)
  FROM (SELECT 0 AS n, :'target_user_key' AS external_id
        UNION ALL SELECT n, 'seed-similar-avatar-' || n FROM generate_series(1, 5) AS n) s
  JOIN public.users u ON u.id::text = s.external_id OR u.external_id = s.external_id
ON CONFLICT (user_id) DO UPDATE
    SET display_name = EXCLUDED.display_name,
        summary = EXCLUDED.summary,
        status = 'ready',
        metadata = public.user_avatars.metadata || EXCLUDED.metadata,
        updated_at = now();

TRUNCATE _seed_avatar_map;
INSERT INTO _seed_avatar_map(label, user_id, avatar_id)
SELECT CASE WHEN u.external_id = :'target_user_key' OR u.id::text = :'target_user_key' THEN '本人'
            ELSE regexp_replace(u.external_id, '^seed-similar-avatar-', '相似样本') END,
       u.id, a.id
  FROM public.users u
  JOIN public.user_avatars a ON a.user_id = u.id
 WHERE u.external_id = :'target_user_key' OR u.id::text = :'target_user_key'
    OR u.external_id LIKE 'seed-similar-avatar-%';

-- 每个分身写入第一版画像，并建立身份、性格、表达风格、记忆规则和安全策略。
INSERT INTO public.avatar_versions(avatar_id, version_no, source_type, status, change_summary, snapshot, created_by, activated_at)
SELECT avatar_id, 1, 'system', 'active', 'SQL种子脚本生成的初始画像',
       jsonb_build_object('seed', true, 'variant', label), 'system', now()
  FROM _seed_avatar_map
ON CONFLICT (avatar_id, version_no) DO NOTHING;

UPDATE public.user_avatars a
   SET current_version_id = v.id, status = 'ready', updated_at = now()
  FROM public.avatar_versions v
 WHERE v.avatar_id = a.id AND v.version_no = 1 AND v.status = 'active'
   AND a.id IN (SELECT avatar_id FROM _seed_avatar_map);

INSERT INTO public.avatar_identity(avatar_version_id, display_name, summary, privacy_level, extra)
SELECT v.id, a.display_name, a.summary, 'private', jsonb_build_object('seed_variant', m.label)
  FROM _seed_avatar_map m
  JOIN public.user_avatars a ON a.id = m.avatar_id
  JOIN public.avatar_versions v ON v.avatar_id = a.id AND v.version_no = 1
ON CONFLICT (avatar_version_id) DO NOTHING;

INSERT INTO public.avatar_personality(avatar_version_id, model_name, scores, style_tags, confidence, inference_source, status)
SELECT v.id,
       'seed_big_five',
       jsonb_build_object('openness', 0.78 + (row_number() OVER (ORDER BY m.label) - 1) * 0.01,
                          'conscientiousness', 0.72 - (row_number() OVER (ORDER BY m.label) - 1) * 0.008,
                          'extraversion', 0.45 + (row_number() OVER (ORDER BY m.label) - 1) * 0.02,
                          'agreeableness', 0.68, 'neuroticism', 0.30),
       jsonb_build_array('理性', '好奇', CASE WHEN m.label = '本人' THEN '克制' ELSE '温和' END),
       0.60, 'seed_script', 'unconfirmed'
  FROM _seed_avatar_map m JOIN public.avatar_versions v ON v.avatar_id = m.avatar_id AND v.version_no = 1
ON CONFLICT (avatar_version_id) DO NOTHING;

INSERT INTO public.avatar_styles(avatar_version_id, tone, structure_rules, verbosity, technical_density, sentence_style, uncertainty_style, preferred_registers, avoid_rules)
SELECT v.id, jsonb_build_array('清晰', CASE WHEN m.label = '本人' THEN '克制' ELSE '温和' END),
       jsonb_build_array('先给结论', '再说明依据', '必要时举例'), 'medium', 'high', '短句为主，必要时分点', '明确标注不确定性',
       jsonb_build_array('chat', 'answer'), jsonb_build_array('不编造经历', '不冒充真人')
  FROM _seed_avatar_map m JOIN public.avatar_versions v ON v.avatar_id = m.avatar_id AND v.version_no = 1
ON CONFLICT (avatar_version_id) DO NOTHING;

INSERT INTO public.avatar_memory_rules(avatar_id) SELECT avatar_id FROM _seed_avatar_map ON CONFLICT (avatar_id) DO NOTHING;
INSERT INTO public.avatar_policies(avatar_id) SELECT avatar_id FROM _seed_avatar_map ON CONFLICT (avatar_id) DO NOTHING;

-- 写入一条可检索的种子兴趣记忆；相似样本通过主题后缀保持差异。
INSERT INTO public.avatar_memories(avatar_id, version_id, memory_type, topic, content, structured_data, level, confidence, status, privacy)
SELECT m.avatar_id, v.id, 'interest', '技术与表达',
       CASE WHEN m.label = '本人' THEN '关注技术如何影响普通人的生活与表达。' ELSE '关注技术如何影响普通人的生活与表达，且偏好不同的讨论切入点。' END,
       jsonb_build_object('seed_variant', m.label), 'middle', 0.60, 'unconfirmed', 'private'
  FROM _seed_avatar_map m JOIN public.avatar_versions v ON v.avatar_id = m.avatar_id AND v.version_no = 1;

COMMIT;

-- 输出生成结果，便于调用方记录本人分身和五个样本的 UUID。
SELECT m.label, m.user_id, m.avatar_id, a.current_version_id AS version_id
  FROM _seed_avatar_map m JOIN public.user_avatars a ON a.id = m.avatar_id
 ORDER BY CASE WHEN m.label = '本人' THEN 0 ELSE 1 END, m.label;
