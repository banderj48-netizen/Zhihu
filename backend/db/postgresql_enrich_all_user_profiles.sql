-- ============================================================
-- 为当前所有未删除用户补齐丰富数字分身画像与知乎原始资料。
-- 约束：不新增重复分身；原始资料使用 platform + external_id 幂等。
-- seed-login-user-2 与 seed-login-user-3 共享技术教育兴趣，但职业与表达风格不同。
-- ============================================================
BEGIN;

CREATE TEMP TABLE _profile_map AS
SELECT u.id AS user_id, u.external_id, a.id AS avatar_id, a.current_version_id AS version_id,
       row_number() OVER (ORDER BY u.external_id)::int AS profile_no
FROM public.users u
JOIN public.user_avatars a ON a.user_id = u.id
WHERE u.deleted_at IS NULL;

-- 为已有分身补充/更新画像身份信息，保留一人一分身约束。
UPDATE public.avatar_identity i
SET summary = CASE WHEN m.external_id IN ('seed-login-user-2','seed-login-user-3')
                   THEN '长期关注技术、教育与知识传播，重视把复杂问题讲清楚。'
                   ELSE '关注个人成长、真实经验与可执行的方法论。' END,
    occupation = CASE m.external_id
        WHEN 'xie' THEN '产品与技术实践者'
        WHEN 'seed-login-user-2' THEN '教育产品经理'
        WHEN 'seed-login-user-3' THEN '软件工程师'
        WHEN 'seed-login-user-4' THEN '独立研究者'
        WHEN 'seed-login-user-5' THEN '内容策划编辑'
        ELSE '数据分析师' END,
    location = CASE m.profile_no
        WHEN 1 THEN '北京' WHEN 2 THEN '上海' WHEN 3 THEN '杭州'
        WHEN 4 THEN '深圳' WHEN 5 THEN '成都' ELSE '广州' END,
    age = 24 + m.profile_no,
    extra = jsonb_build_object('profile_quality','rich_seed','interests_similar_group', CASE WHEN m.external_id IN ('seed-login-user-2','seed-login-user-3') THEN 'technology-education' ELSE NULL END)
FROM _profile_map m
WHERE i.avatar_version_id = m.version_id;

-- 为每个用户写入四类可检索记忆；相似用户的共同兴趣使用相同主题和核心事实。
INSERT INTO public.avatar_memories (avatar_id, version_id, memory_type, topic, content, structured_data, level, score, confidence, status, privacy, evidence_count)
SELECT m.avatar_id, m.version_id, x.memory_type, x.topic, x.content,
       jsonb_build_object('seed','rich_profile','external_id',m.external_id,'similar_interest',m.external_id IN ('seed-login-user-2','seed-login-user-3')),
       'middle', x.score, 0.82, 'confirmed', 'private', 1
FROM _profile_map m
CROSS JOIN LATERAL (VALUES
 ('interest','技术与教育','关注技术如何改善学习效率、知识获取与普通人的决策质量。',0.92::numeric),
 ('experience','工作经历','有持续参与项目协作、资料整理和复盘总结的经历，偏好用事实验证判断。',0.76::numeric),
 ('opinion','信息质量','认为好的回答应区分事实、推断和个人观点，并给出可追溯依据。',0.88::numeric),
 ('preference','表达偏好','喜欢结构清楚、先结论后依据、避免夸张和空泛表达的内容。',0.84::numeric)
) AS x(memory_type,topic,content,score)
WHERE NOT EXISTS (SELECT 1 FROM public.avatar_memories z WHERE z.avatar_id=m.avatar_id AND z.topic=x.topic AND z.status <> 'rejected');

-- 每个用户三篇原始资料，作为关键词检索和后续向量同步的真实候选来源。
INSERT INTO public.source_documents (user_id, avatar_id, platform, external_id, document_type, title, content, source_url, published_at, content_hash, metadata)
SELECT m.user_id, m.avatar_id, 'zhihu', m.external_id || '-profile-' || d.n, d.document_type, d.title, d.content,
       'https://www.zhihu.com/question/' || (10000000 + row_number() OVER (ORDER BY m.external_id))::text,
       now() - (d.n || ' days')::interval, md5(d.content),
       jsonb_build_object('import_mode','database_simulation','original_author',m.external_id,'content_language','zh-CN','similar_interest_group',m.external_id IN ('seed-login-user-2','seed-login-user-3'))
FROM _profile_map m
CROSS JOIN LATERAL (VALUES
 (1,'answer','如何把复杂技术问题讲给非技术用户','我会先明确问题边界，再用生活化例子解释关键机制，最后列出仍然不确定的部分。这样既保留准确性，也让读者知道下一步如何验证。'),
 (2,'article','一次项目复盘：从争论到可验证的方案','团队意见不一致时，与其继续争论偏好，不如把分歧改写成可验证假设，约定指标、时间窗口和失败条件。复盘时记录证据，比记录谁说服了谁更有价值。'),
 (3,'answer','我如何整理长期积累的知识','我把资料分为事实、案例、观点和待验证线索，并给每条资料保留来源、时间和适用范围。知识库不是收藏夹，而是帮助未来做出更好判断的工具。')
) AS d(n,document_type,title,content)
ON CONFLICT (platform, external_id) DO UPDATE SET title=EXCLUDED.title, content=EXCLUDED.content, content_hash=EXCLUDED.content_hash, metadata=EXCLUDED.metadata, imported_at=now();

-- 将原始资料中的表达样例绑定回分身，形成可用于风格检索的闭环。
INSERT INTO public.avatar_style_examples (avatar_id, register, text, source_document_id)
SELECT m.avatar_id, 'answer', '我会先给结论，再说明依据；如果证据不足，会明确标注不确定性。', s.id
FROM _profile_map m JOIN public.source_documents s ON s.avatar_id=m.avatar_id AND s.external_id=m.external_id || '-profile-1'
WHERE NOT EXISTS (SELECT 1 FROM public.avatar_style_examples e WHERE e.avatar_id=m.avatar_id AND e.source_document_id=s.id);

-- 明确检索策略和安全策略，保证画像在接口测试中可解释、不可臆造。
UPDATE public.avatar_memory_rules r SET top_k=12, use_vector_search=true, use_keyword_search=true, prefer_confirmed=true, prefer_recent_opinions=true,
    confidence_policy=jsonb_build_object('minimum',0.55,'show_uncertainty_below',0.75), updated_at=now()
FROM _profile_map m WHERE r.avatar_id=m.avatar_id;
UPDATE public.avatar_policies p SET can_use_unconfirmed_memory=false, can_present_unconfirmed_as_fact=false, can_invent_user_experience=false, can_invent_user_opinion=false,
    must_show_uncertainty=true, must_keep_citations=true, sensitive_attributes_policy='redact', external_action_requires_confirmation=true,
    custom_rules=jsonb_build_object('seed_profile',true,'require_source_citation',true)
FROM _profile_map m WHERE p.avatar_id=m.avatar_id;

COMMIT;

SELECT m.external_id, count(DISTINCT m.avatar_id) AS avatar_count, count(DISTINCT v.id) AS active_version_count,
       count(DISTINCT mem.id) AS memory_count, count(DISTINCT s.id) AS source_document_count
FROM _profile_map m
JOIN public.avatar_versions v ON v.id=m.version_id AND v.status='active'
LEFT JOIN public.avatar_memories mem ON mem.avatar_id=m.avatar_id
LEFT JOIN public.source_documents s ON s.avatar_id=m.avatar_id
GROUP BY m.external_id ORDER BY m.external_id;
