// 数字分身初始化向导。
// 流程：导入知乎资料 → 性格测试 → 选择兴趣与擅长 → 领域观点题 → 限时社交情景题 → 填写基础身份并生成画像。
// 进入时创建（或恢复）唯一的初始化会话，按已保存的 input_data 自动定位到未完成的步骤。
'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { Check, HeartHandshake } from 'lucide-react';
import { api, getMe, setApiUserId, type DomainNode, type InitSession, type MePayload } from '../../lib/api';
import { ErrorBanner, LoadingBlock } from './steps/shared';
import ImportStep from './steps/ImportStep';
import PersonalityStep from './steps/PersonalityStep';
import DomainsStep from './steps/DomainsStep';
import OpinionStep from './steps/OpinionStep';
import SocialStep from './steps/SocialStep';
import IdentityStep from './steps/IdentityStep';

const STEP_LABELS = ['导入资料', '性格测试', '兴趣领域', '观点问答', '情景反应', '生成画像'];
// 每一步完成后写入会话 input_data 的键，用于断点续做。
const STEP_KEYS = ['zhihu-import', 'personality', 'domains', 'opinion-answers', 'social-answers'];

function stepperIndex(session: InitSession | null): number {
  if (!session) return 0;
  if (session.status === 'completed') return 5;
  const data = session.input_data || {};
  for (let i = 0; i < STEP_KEYS.length; i += 1) {
    if (!data[STEP_KEYS[i]]) return i;
  }
  return 5;
}

function Stepper({ current }: { current: number }) {
  return (
    <ol className="flex items-center gap-1 sm:gap-2">
      {STEP_LABELS.map((label, index) => {
        const done = index < current;
        const active = index === current;
        return (
          <li key={label} className="flex items-center gap-1 sm:gap-2">
            {index > 0 && <span className="h-px w-3 bg-[#e3e6e8] sm:w-6" />}
            <span
              className={
                'flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs ' +
                (active ? 'bg-[#e6f3ff] font-medium text-[#0084ff]' : done ? 'text-[#0084ff]' : 'text-[#8590a6]')
              }
            >
              <span
                className={
                  'flex h-5 w-5 items-center justify-center rounded-full text-[11px] ' +
                  (active ? 'bg-[#0084ff] text-white' : done ? 'bg-[#0084ff] text-white' : 'bg-[#ebedf0] text-white')
                }
              >
                {done ? <Check size={11} /> : index + 1}
              </span>
              <span className="hidden sm:inline">{label}</span>
            </span>
          </li>
        );
      })}
    </ol>
  );
}

export default function InitializationPage() {
  const [me, setMe] = useState<MePayload | null>(null);
  const [session, setSession] = useState<InitSession | null>(null);
  const [catalog, setCatalog] = useState<DomainNode[]>([]);
  const [step, setStep] = useState(0);
  const [bootError, setBootError] = useState('');

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        // 已登录则使用真实知乎身份；本地未登录时回退到联调账号，保证流程可体验。
        let profile: MePayload;
        try {
          profile = await getMe();
        } catch {
          profile = {
            user_id: 'local-demo-user',
            avatar_id: null,
            avatar_status: 'not_created',
            zhihu_connected: false,
            zhihu: { fullname: '本地体验用户', avatar_url: '', headline: '使用本地联调账号初始化数字分身' },
          };
        }
        if (cancelled) return;
        setApiUserId(profile.user_id);
        setMe(profile);
        // 创建或恢复当前用户唯一的初始化会话（后端按 user_id 幂等）。
        const created = await api<InitSession>('/v1/twin/initializations', 'POST', {});
        if (cancelled) return;
        setSession(created);
        setStep(stepperIndex(created));
        // 领域目录供观点题展示 topic 标签使用。
        const domains = await api<{ items: DomainNode[] }>('/v1/domains');
        if (!cancelled) setCatalog(domains.items || []);
      } catch (error) {
        if (!cancelled) setBootError(error instanceof Error ? error.message : '初始化服务暂不可用');
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const handleStepDone = useCallback((updated: InitSession) => {
    setSession(updated);
    setStep((prev) => Math.min(prev + 1, STEP_LABELS.length - 1));
    if (typeof window !== 'undefined') window.scrollTo({ top: 0 });
  }, []);

  const goBack = useCallback(() => setStep((prev) => Math.max(prev - 1, 0)), []);

  const body = useMemo(() => {
    if (!session || !me) return <LoadingBlock text="正在进入初始化…" />;
    const stepProps = { session, me, catalog, onDone: handleStepDone, onBack: goBack };
    switch (step) {
      case 0:
        return <ImportStep {...stepProps} />;
      case 1:
        return <PersonalityStep {...stepProps} />;
      case 2:
        return <DomainsStep {...stepProps} />;
      case 3:
        return <OpinionStep {...stepProps} />;
      case 4:
        return <SocialStep {...stepProps} />;
      default:
        return <IdentityStep {...stepProps} />;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step, session, me, catalog]);

  return (
    <main className="min-h-screen bg-[#f6f6f6] text-[#1a1a1a]">
      <header className="sticky top-0 z-30 border-b border-[#ebebeb] bg-white/95 backdrop-blur">
        <div className="mx-auto flex h-16 max-w-2xl items-center justify-between px-5">
          <Link href="/" className="flex items-center gap-2 text-[18px] font-semibold">
            <span className="flex h-8 w-8 items-center justify-center rounded-md bg-[#0084ff] text-white">
              <HeartHandshake size={17} />
            </span>
            知交桥
          </Link>
          <Link href="/" className="text-sm text-[#8590a6] hover:text-[#0084ff]">
            暂时退出
          </Link>
        </div>
      </header>
      <div className="mx-auto max-w-2xl px-5 py-6">
        <div className="mb-6 rounded-2xl border border-[#ebebeb] bg-white px-4 py-3 shadow-sm">
          <Stepper current={step} />
        </div>
        {bootError ? <ErrorBanner message={bootError} /> : body}
        <p className="mt-6 text-center text-xs leading-5 text-[#8590a6]">
          初始化数据仅用于生成你的数字分身画像，答题过程可以中途刷新，我们会从上一步继续。
        </p>
      </div>
    </main>
  );
}
