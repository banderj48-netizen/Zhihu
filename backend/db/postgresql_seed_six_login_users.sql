-- ============================================================
-- 模拟六个授权登录用户及其数字分身。
-- 本脚本适用于 zhihu 数据库；OAuth 系统不保存本地密码，external_id
-- 用于模拟知乎用户标识。脚本可重复执行，不会创建重复用户或分身。
-- ============================================================
BEGIN;

CREATE TEMP TABLE _six_login_users (label text PRIMARY KEY, external_id text UNIQUE, user_id uuid, avatar_id uuid, version_id uuid) ON COMMIT DROP;

INSERT INTO public.users (external_id)
SELECT CASE WHEN n = 1 THEN 'xie' ELSE 'seed-login-user-' || n END
FROM generate_series(1, 6) AS s(n)
ON CONFLICT (external_id) DO UPDATE SET updated_at = now(), deleted_at = NULL;

INSERT INTO _six_login_users (label, external_id, user_id)
SELECT CASE WHEN n = 1 THEN '用户xie' ELSE '模拟用户' || n END,
       CASE WHEN n = 1 THEN 'xie' ELSE 'seed-login-user-' || n END, u.id
FROM generate_series(1, 6) AS s(n)
JOIN public.users u ON u.external_id = CASE WHEN n = 1 THEN 'xie' ELSE 'seed-login-user-' || n END;

INSERT INTO public.user_avatars (user_id, display_name, summary, status, metadata)
SELECT user_id, label || '的数字分身', '用于后端接口联调的模拟授权用户数字分身', 'ready',
       jsonb_build_object('seed_script', 'postgresql_seed_six_login_users.sql', 'simulated_login', true)
FROM _six_login_users
ON CONFLICT (user_id) DO UPDATE SET status = 'ready', updated_at = now(), metadata = public.user_avatars.metadata || EXCLUDED.metadata;

UPDATE _six_login_users m SET avatar_id = a.id
FROM public.user_avatars a WHERE a.user_id = m.user_id;

INSERT INTO public.avatar_versions (avatar_id, version_no, source_type, status, change_summary, snapshot, created_by, activated_at)
SELECT avatar_id, 1, 'system_merge', 'active', '模拟登录用户初始画像', jsonb_build_object('simulated_login', true, 'label', label), 'system', now()
FROM _six_login_users ON CONFLICT (avatar_id, version_no) DO NOTHING;

UPDATE _six_login_users m SET version_id = v.id
FROM public.avatar_versions v WHERE v.avatar_id = m.avatar_id AND v.version_no = 1;

UPDATE public.user_avatars a SET current_version_id = m.version_id, status = 'ready', updated_at = now()
FROM _six_login_users m WHERE a.id = m.avatar_id;

INSERT INTO public.avatar_identity (avatar_version_id, display_name, summary, privacy_level)
SELECT version_id, label || '的数字分身', '模拟授权登录用户画像', 'private' FROM _six_login_users
ON CONFLICT (avatar_version_id) DO NOTHING;

INSERT INTO public.avatar_personality (avatar_version_id, model_name, scores, style_tags, confidence, inference_source, status)
SELECT version_id, 'seed_login', jsonb_build_object('openness', 0.70, 'conscientiousness', 0.70, 'extraversion', 0.50, 'agreeableness', 0.70, 'neuroticism', 0.30), jsonb_build_array('清晰', '理性'), 0.50, 'seed_script', 'unconfirmed'
FROM _six_login_users ON CONFLICT (avatar_version_id) DO NOTHING;

INSERT INTO public.avatar_styles (avatar_version_id, tone, structure_rules, verbosity, technical_density, sentence_style, uncertainty_style, preferred_registers, avoid_rules)
SELECT version_id, jsonb_build_array('清晰'), jsonb_build_array('先给结论', '再说明依据'), 'medium', 'medium', '短句为主', '明确标注不确定性', jsonb_build_array('chat', 'answer'), jsonb_build_array('不编造经历')
FROM _six_login_users ON CONFLICT (avatar_version_id) DO NOTHING;

INSERT INTO public.avatar_memory_rules (avatar_id) SELECT avatar_id FROM _six_login_users ON CONFLICT (avatar_id) DO NOTHING;
INSERT INTO public.avatar_policies (avatar_id) SELECT avatar_id FROM _six_login_users ON CONFLICT (avatar_id) DO NOTHING;

INSERT INTO public.avatar_memories (avatar_id, version_id, memory_type, topic, content, structured_data, level, confidence, status, privacy)
SELECT avatar_id, version_id, 'interest', '接口联调', '关注数字分身后端接口的正确性与可观测性。', jsonb_build_object('simulated_login', true), 'middle', 0.50, 'unconfirmed', 'private'
FROM _six_login_users;

COMMIT;

SELECT u.external_id, u.id AS user_id, a.id AS avatar_id, a.current_version_id AS version_id, a.status
FROM public.users u JOIN public.user_avatars a ON a.user_id = u.id
WHERE u.external_id = 'xie' OR u.external_id LIKE 'seed-login-user-%'
ORDER BY u.external_id;
