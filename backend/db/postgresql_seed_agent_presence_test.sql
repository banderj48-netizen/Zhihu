-- ============================================================
-- 为两个指定测试 Agent 准备所有已实现场景的空闲在场数据。
-- 本脚本只用于手动接口测试，不创建新用户、不创建新数字分身。
-- ============================================================
BEGIN;

-- 测试前释放两个 Agent 可能残留的旧占用，避免上一次中断影响本次匹配。
UPDATE public.agent_scene_presence p
SET status = 'idle', current_dialogue_run_id = NULL, updated_at = now()
FROM public.user_avatars a
JOIN public.users u ON u.id = a.user_id
WHERE p.avatar_id = a.id
  AND u.external_id IN ('xie', 'seed-login-user-2');

-- 为两个测试 Agent 在全部已实现场景登记空闲状态。
INSERT INTO public.agent_scene_presence (avatar_id, scene_id, status, display_summary)
SELECT a.id,
       s.scene_id,
       'idle',
       jsonb_build_object('display_name', a.display_name, 'test_fixture', true, 'external_id', u.external_id)
FROM public.users u
JOIN public.user_avatars a ON a.user_id = u.id AND a.status <> 'archived'
CROSS JOIN (VALUES ('cafe'), ('library'), ('bar'), ('theater'), ('lecture')) AS s(scene_id)
WHERE u.external_id IN ('xie', 'seed-login-user-2')
ON CONFLICT (avatar_id, scene_id) DO UPDATE
SET status = 'idle', current_dialogue_run_id = NULL,
    display_summary = EXCLUDED.display_summary, updated_at = now();

COMMIT;

SELECT u.external_id, p.scene_id, p.status, p.avatar_id
FROM public.agent_scene_presence p
JOIN public.user_avatars a ON a.id = p.avatar_id
JOIN public.users u ON u.id = a.user_id
WHERE u.external_id IN ('xie', 'seed-login-user-2')
ORDER BY u.external_id, p.scene_id;
