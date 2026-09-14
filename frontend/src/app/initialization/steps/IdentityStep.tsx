// 第 6 步：填写基础身份并生成初始用户画像。
// 基础身份是唯一需要用户手写的画像内容；其余画像由前面的答题结合后端规则生成。
// 完成后展示 avatar_id / version_id 与生成摘要，并返回首页入口。
'use client';

import { useState } from 'react';
import Link from 'next/link';
import { CheckCircle2, Sparkles } from 'lucide-react';
import { api, type InitSession } from '../../../lib/api';
import { ErrorBanner, PrimaryButton, SecondaryButton, StepCard, shortId, type StepProps } from './shared';

type Identity = {
  display_name: string;
  summary: string;
  occupation: string;
  location: string;
  age: string;
  privacy_level: 'private' | 'public';
};

const STAGES = ['读取答题记录…', '写入画像版本…', '生成记忆与证据链…', '激活数字分身…'];

export default function IdentityStep({ session, me, onBack }: StepProps) {
  const completed = session.status === 'completed';
  const [identity, setIdentity] = useState<Identity>({
    display_name: me.zhihu?.fullname || '',
    summary: me.zhihu?.headline || '',
    occupation: '',
    location: '',
    age: '',
    privacy_level: 'private',
  });
  const [submitting, setSubmitting] = useState(false);
  const [stage, setStage] = useState(0);
  const [result, setResult] = useState<Record<string, any> | null>(
    completed ? session.generated_profile || {} : null
  );
  const [error, setError] = useState('');

  const submit = async () => {
    setSubmitting(true);
    setError('');
    const stageTimer = setInterval(() => setStage((prev) => Math.min(prev + 1, STAGES.length - 1)), 900);
    try {
      const payload = await api<Record<string, any>>(`/v1/twin/initializations/${session.id}/complete`, 'POST', {
        identity: {
          display_name: identity.display_name.trim(),
          summary: identity.summary.trim(),
          occupation: identity.occupation.trim(),
          location: identity.location.trim(),
          age: identity.age ? Number(identity.age) : null,
          privacy_level: identity.privacy_level,
        },
      });
      setResult(payload);
    } catch (e) {
      setError(e instanceof Error ? e.message : '画像生成失败，请重试');
    } finally {
      clearInterval(stageTimer);
      setSubmitting(false);
    }
  };

  if (result) {
    const status = String(result.status || 'ready');
    const statusLabel =
      status === 'already_initialized'
        ? '分身此前已生成，无需重复初始化'
        : status === 'ready' || status === 'initialized'
          ? '已激活'
          : status;
    return (
      <StepCard step={6} total={6} title="数字分身已生成" description="初始化完成，你的看山可以进入小镇与其他分身相遇了。">
        <div className="flex flex-col items-center py-4">
          <span className="flex h-14 w-14 items-center justify-center rounded-full bg-[#e6f3ff] text-[#0084ff]">
            <CheckCircle2 size={30} />
          </span>
          <p className="mt-4 text-lg font-semibold">
            {status === 'already_initialized' ? '分身此前已生成，无需重复初始化' : '初始用户画像已生成并激活'}
          </p>
          <div className="mt-5 w-full space-y-2 rounded-xl bg-[#f6f7f8] p-4 text-sm">
            <div className="flex justify-between">
              <span className="text-[#8590a6]">数字分身</span>
              <span className="font-mono">{shortId(String(result.avatar_id || ''))}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-[#8590a6]">画像版本</span>
              <span className="font-mono">{shortId(String(result.version_id || ''))}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-[#8590a6]">分身状态</span>
              <span>{statusLabel}</span>
            </div>
          </div>
          <p className="mt-4 text-center text-xs leading-5 text-[#8590a6]">
            兴趣、专长、观点与行为记忆已写入画像库并进入检索索引，后续对话中分身会逐步确认这些记忆。
          </p>
          <div className="mt-6 flex w-full flex-col gap-2 sm:flex-row">
            <Link
              href="/"
              className="flex-1 rounded-md border border-[#e3e6e8] bg-white px-4 py-2.5 text-center text-sm text-[#646a73] hover:bg-[#f6f6f6]"
            >
              返回个人中心
            </Link>
            <Link
              href="/"
              className="flex flex-1 items-center justify-center gap-2 rounded-md bg-[#0084ff] px-4 py-2.5 text-sm font-medium text-white"
            >
              <Sparkles size={15} />
              进入知交桥
            </Link>
          </div>
        </div>
      </StepCard>
    );
  }

  const disabled = !identity.display_name.trim();

  return (
    <StepCard
      step={6}
      total={6}
      title="基础身份与生成画像"
      description="基础身份需要你亲手填写（其余画像已由前面几步的作答生成）。点击生成后，我们会写入画像版本并激活你的数字分身。"
    >
      <div className="space-y-4">
        <div>
          <label className="mb-1.5 block text-sm font-medium">昵称 *</label>
          <input
            value={identity.display_name}
            onChange={(event) => setIdentity((prev) => ({ ...prev, display_name: event.target.value }))}
            maxLength={30}
            placeholder="数字分身对外的名字"
            className="w-full rounded-lg border border-[#e3e6e8] bg-white px-3 py-2.5 text-sm outline-none focus:border-[#0084ff]"
          />
        </div>
        <div>
          <label className="mb-1.5 block text-sm font-medium">一句话介绍</label>
          <input
            value={identity.summary}
            onChange={(event) => setIdentity((prev) => ({ ...prev, summary: event.target.value }))}
            maxLength={80}
            placeholder="你希望别人如何认识你"
            className="w-full rounded-lg border border-[#e3e6e8] bg-white px-3 py-2.5 text-sm outline-none focus:border-[#0084ff]"
          />
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label className="mb-1.5 block text-sm font-medium">职业</label>
            <input
              value={identity.occupation}
              onChange={(event) => setIdentity((prev) => ({ ...prev, occupation: event.target.value }))}
              maxLength={30}
              placeholder="如：后端工程师"
              className="w-full rounded-lg border border-[#e3e6e8] bg-white px-3 py-2.5 text-sm outline-none focus:border-[#0084ff]"
            />
          </div>
          <div>
            <label className="mb-1.5 block text-sm font-medium">常居地</label>
            <input
              value={identity.location}
              onChange={(event) => setIdentity((prev) => ({ ...prev, location: event.target.value }))}
              maxLength={30}
              placeholder="如：上海"
              className="w-full rounded-lg border border-[#e3e6e8] bg-white px-3 py-2.5 text-sm outline-none focus:border-[#0084ff]"
            />
          </div>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label className="mb-1.5 block text-sm font-medium">年龄（选填）</label>
            <input
              value={identity.age}
              onChange={(event) => setIdentity((prev) => ({ ...prev, age: event.target.value.replace(/\D/g, '').slice(0, 3) }))}
              inputMode="numeric"
              placeholder="如：26"
              className="w-full rounded-lg border border-[#e3e6e8] bg-white px-3 py-2.5 text-sm outline-none focus:border-[#0084ff]"
            />
          </div>
          <div>
            <label className="mb-1.5 block text-sm font-medium">画像可见性</label>
            <select
              value={identity.privacy_level}
              onChange={(event) => setIdentity((prev) => ({ ...prev, privacy_level: event.target.value as Identity['privacy_level'] }))}
              className="w-full rounded-lg border border-[#e3e6e8] bg-white px-3 py-2.5 text-sm outline-none focus:border-[#0084ff]"
            >
              <option value="private">私有（默认，仅自己与分身可见）</option>
              <option value="public">公开</option>
            </select>
          </div>
        </div>
      </div>

      {submitting && (
        <div className="mt-5 rounded-xl bg-[#f0f7ff] p-4">
          <p className="flex items-center gap-2 text-sm text-[#2f6fae]">
            <span className="h-2 w-2 animate-pulse rounded-full bg-[#0084ff]" />
            {STAGES[stage]}
          </p>
        </div>
      )}
      <ErrorBanner message={error} />
      <div className="mt-6 flex items-center justify-between">
        <SecondaryButton onClick={onBack}>上一步</SecondaryButton>
        <PrimaryButton onClick={submit} disabled={disabled} loading={submitting}>
          生成数字分身
        </PrimaryButton>
      </div>
    </StepCard>
  );
}
