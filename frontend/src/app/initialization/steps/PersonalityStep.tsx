// 第 2 步：性格测试（IPIP 大五 50 题）。
// 10 题一页作答，全部作答后提交评分；评分结果写入初始化会话。
// 跳过测试不阻塞流程（后端策略允许），画像将缺少自评性格维度。
'use client';

import { useEffect, useState } from 'react';
import { api, type InitSession } from '../../../lib/api';
import { ErrorBanner, LoadingBlock, PrimaryButton, SecondaryButton, StepCard, TextButton, type StepProps } from './shared';

const PAGE_SIZE = 10;

type Dimension = { id: string; label: string };
type Item = { id: string; text: string };
type Questions = {
  instrument_version: string;
  scale: { min: number; max: number; labels: string[] };
  dimensions: Dimension[];
  items: Item[];
};
type Assessment = {
  status: string;
  scores: Record<string, number | null> | null;
  style_tags?: string[];
  validity?: { flags?: string[] };
};

function ScoreBars({ assessment, dimensions }: { assessment: Assessment; dimensions: Dimension[] }) {
  const rows = dimensions.length ? dimensions : Object.keys(assessment.scores || {}).map((id) => ({ id, label: id }));
  return (
    <div className="space-y-3">
      {rows.map((dim) => {
        const score = assessment.scores?.[dim.id];
        const percent = typeof score === 'number' ? Math.round((score / 10) * 100) : 0;
        return (
          <div key={dim.id}>
            <div className="mb-1 flex items-center justify-between text-sm">
              <span>{dim.label}</span>
              <span className="text-[#8590a6]">{typeof score === 'number' ? `${score.toFixed(1)} / 10` : '未测评'}</span>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-[#eef0f2]">
              <div className="h-full rounded-full bg-[#0084ff]" style={{ width: `${percent}%` }} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

export default function PersonalityStep({ session, onDone, onBack }: StepProps) {
  const saved = session.input_data?.personality as Assessment | undefined;
  const [questions, setQuestions] = useState<Questions | null>(null);
  const [error, setError] = useState('');
  const [answers, setAnswers] = useState<Record<string, number>>({});
  const [page, setPage] = useState(0);
  const [result, setResult] = useState<Assessment | null>(saved?.scores ? saved : null);
  const [savedSession, setSavedSession] = useState<InitSession | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    api<Questions>('/v1/personality/questions')
      .then(setQuestions)
      .catch((e) => setError(e instanceof Error ? e.message : '题库加载失败'));
  }, []);

  if (!questions) {
    return (
      <StepCard step={2} total={6} title="性格测试">
        <ErrorBanner message={error} />
        <LoadingBlock text="正在加载性格测试题…" />
      </StepCard>
    );
  }

  // 已有评分结果（本机续做或重新进入）直接展示。
  if (result) {
    return (
      <StepCard step={2} total={6} title="性格测试完成" description="以下是根据你的作答生成的大五性格评分，将写入数字分身的性格画像。">
        <ScoreBars assessment={result} dimensions={questions.dimensions} />
        {result.status === 'skipped' && (
          <p className="mt-4 rounded-lg bg-[#fffaf0] p-3 text-sm text-[#8d5b35]">本次跳过了性格测试，画像暂无自评性格维度。</p>
        )}
        {!!result.style_tags?.length && (
          <div className="mt-4 flex flex-wrap gap-2">
            {result.style_tags.map((tag) => (
              <span key={tag} className="rounded-md bg-[#f0f7ff] px-2.5 py-1 text-xs text-[#2f6fae]">
                {tag}
              </span>
            ))}
          </div>
        )}
        <div className="mt-6 flex items-center justify-between">
          <SecondaryButton onClick={onBack}>上一步</SecondaryButton>
          <PrimaryButton onClick={() => onDone(savedSession || session)}>下一步</PrimaryButton>
        </div>
      </StepCard>
    );
  }

  const items = questions.items;
  const totalPages = Math.ceil(items.length / PAGE_SIZE);
  const pageItems = items.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
  const pageUnanswered = pageItems.filter((item) => !answers[item.id]).length;
  const overallAnswered = Object.keys(answers).length;

  const submit = async (skipped: boolean) => {
    setSubmitting(true);
    setError('');
    try {
      const requestKey = `init_${session.id}`;
      const assessment = skipped
        ? await api<Assessment>('/v1/personality/skip', 'POST', { request_key: requestKey })
        : await api<Assessment>('/v1/personality/assessments', 'POST', {
            answers,
            notes: null,
            request_key: requestKey,
          });
      const updated = await api<InitSession>(`/v1/twin/initializations/${session.id}/personality`, 'POST', {
        data: assessment,
      });
      // 先展示评分结果，由用户点击「下一步」再进入领域选择。
      setSavedSession(updated);
      setResult(assessment);
    } catch (e) {
      setError(e instanceof Error ? e.message : '提交失败，请重试');
      setSubmitting(false);
    }
  };

  return (
    <StepCard
      step={2}
      total={6}
      title="性格测试"
      description="共 50 道描述题，请按自己的真实情况作答，没有对错之分。结果只用于生成数字分身的性格画像。"
    >
      <div className="mb-4 flex items-center justify-between text-xs text-[#8590a6]">
        <span>
          第 {page + 1} / {totalPages} 页 · 已答 {overallAnswered} / {items.length} 题
        </span>
        {pageUnanswered > 0 && <span className="text-[#c45656]">本页还有 {pageUnanswered} 题未作答</span>}
      </div>
      <div className="space-y-4">
        {pageItems.map((item, index) => (
          <div key={item.id} className="rounded-xl border border-[#ebebeb] p-4">
            <p className="text-sm leading-6">
              <span className="mr-2 text-[#8590a6]">{page * PAGE_SIZE + index + 1}.</span>
              {item.text}
            </p>
            <div className="mt-3 grid grid-cols-5 gap-1.5">
              {questions.scale.labels.map((label, valueIndex) => {
                const value = questions.scale.min + valueIndex;
                const active = answers[item.id] === value;
                return (
                  <button
                    key={label}
                    onClick={() => setAnswers((prev) => ({ ...prev, [item.id]: value }))}
                    className={
                      'rounded-lg border px-1 py-2 text-xs transition ' +
                      (active ? 'border-[#0084ff] bg-[#f0f7ff] font-medium text-[#0084ff]' : 'border-[#e3e6e8] text-[#646a73] hover:border-[#c9dcf2]')
                    }
                  >
                    {label}
                  </button>
                );
              })}
            </div>
          </div>
        ))}
      </div>
      <ErrorBanner message={error} />
      <div className="mt-6 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          {page > 0 && <SecondaryButton onClick={() => setPage((p) => p - 1)}>上一页</SecondaryButton>}
        </div>
        <div className="flex items-center gap-4">
          <TextButton onClick={() => submit(true)}>跳过测试</TextButton>
          {page < totalPages - 1 ? (
            <PrimaryButton onClick={() => setPage((p) => p + 1)} disabled={pageUnanswered > 0}>
              下一页
            </PrimaryButton>
          ) : (
            <PrimaryButton onClick={() => submit(false)} disabled={overallAnswered < items.length} loading={submitting}>
              提交测试
            </PrimaryButton>
          )}
        </div>
      </div>
    </StepCard>
  );
}
