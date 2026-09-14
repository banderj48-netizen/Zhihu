// 第 5 步：现实社交情景选择题（限时 13 秒）。
// 每题展示前先请求后端登记 presented_at（服务端时钟），倒计时结束自动记为超时；
// 真实耗时 elapsed_seconds 由前端按本地时钟计算并如实上报，超过 13 秒的作答
// 后端不会计入行为记忆（详见 social-question-contract.md）。
'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { Timer } from 'lucide-react';
import { api, type InitSession } from '../../../lib/api';
import { ErrorBanner, LoadingBlock, OptionRow, PrimaryButton, SecondaryButton, StepCard, type StepProps } from './shared';

const FALLBACK_LIMIT = 13;

type Option = { id: string; label: string; requires_custom_text?: boolean };
type Question = {
  question_id: string;
  question_version: number;
  question_type: string;
  scene: string;
  options: Option[];
};
type Answer = {
  question_id: string;
  question_version: number;
  scene: string;
  topic: string;
  level: string;
  selected_option_id: string | null;
  custom_text: string | null;
  reaction: string;
  presented_at: string | null;
  submitted_at: string | null;
  elapsed_seconds: number | null;
  status: 'counted' | 'timeout';
};
type SavedAnswers = { answers?: Answer[] };

export default function SocialStep({ session, onDone, onBack }: StepProps) {
  const saved = session.input_data?.['social-answers'] as SavedAnswers | undefined;
  const [questions, setQuestions] = useState<Question[] | null>(null);
  const [limit, setLimit] = useState(FALLBACK_LIMIT);
  const [current, setCurrent] = useState(0);
  const [answers, setAnswers] = useState<Answer[]>([]);
  const [presentedAt, setPresentedAt] = useState<{ server: string | null; local: number } | null>(null);
  const [remaining, setRemaining] = useState(FALLBACK_LIMIT);
  const [timedOut, setTimedOut] = useState(false);
  const [chosen, setChosen] = useState<string>('');
  const [customText, setCustomText] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const lockedRef = useRef(false);

  useEffect(() => {
    if (saved?.answers?.length) {
      setQuestions([]);
      return;
    }
    api<{ questions: Question[]; time_limit_seconds: number }>(
      `/v1/twin/initializations/${session.id}/social-questions`,
      'POST',
      { count: 5 }
    )
      .then((payload) => {
        setQuestions(payload.questions || []);
        setLimit(payload.time_limit_seconds || FALLBACK_LIMIT);
      })
      .catch((e) => setError(e instanceof Error ? e.message : '题目生成失败'));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 展示第 current 题时：请求服务端打点并启动倒计时。
  const showQuestion = useCallback(
    async (question: Question) => {
      lockedRef.current = false;
      setTimedOut(false);
      setChosen('');
      setCustomText('');
      setRemaining(limit);
      const localStart = Date.now();
      setPresentedAt({ server: null, local: localStart });
      try {
        const stamped = await api<{ presented_at: string }>(`/v1/twin/social-questions/${question.question_id}/present`, 'POST');
        setPresentedAt((prev) => (prev ? { ...prev, server: stamped.presented_at } : prev));
      } catch {
        // 打点失败不阻塞：耗时按本地时钟计算。
      }
    },
    [limit]
  );

  useEffect(() => {
    if (!questions || questions.length === 0 || current >= questions.length) return;
    showQuestion(questions[current]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [current, questions]);

  // 倒计时：每 0.1 秒刷新一次显示，归零后锁定本题。
  useEffect(() => {
    if (!presentedAt) return;
    const started = presentedAt.local;
    const timer = setInterval(() => {
      const left = limit - (Date.now() - started) / 1000;
      if (left <= 0) {
        setRemaining(0);
        setTimedOut(true);
        lockedRef.current = true;
        clearInterval(timer);
      } else {
        setRemaining(left);
      }
    }, 100);
    return () => clearInterval(timer);
  }, [presentedAt, limit]);

  const currentQuestion = questions && current < questions.length ? questions[current] : null;

  const buildAnswer = (optionId: string | null, custom: string | null): Answer | null => {
    if (!currentQuestion || !presentedAt) return null;
    const submittedLocal = Date.now();
    const elapsed = Number(((submittedLocal - presentedAt.local) / 1000).toFixed(3));
    const option = currentQuestion.options.find((candidate) => candidate.id === optionId);
    const counted = !!optionId && elapsed <= limit;
    return {
      question_id: currentQuestion.question_id,
      question_version: currentQuestion.question_version,
      scene: currentQuestion.scene,
      topic: currentQuestion.scene,
      level: 'middle',
      selected_option_id: optionId,
      custom_text: custom,
      // reaction 是行为记忆的默认文案：自定义答案优先，否则用选项原文。
      reaction: custom || option?.label || '',
      presented_at: presentedAt.server,
      submitted_at: new Date(submittedLocal).toISOString(),
      elapsed_seconds: elapsed,
      status: counted ? 'counted' : 'timeout',
    };
  };

  const advance = (answer: Answer | null) => {
    setAnswers((prev) => [...prev, ...(answer ? [answer] : [])]);
    if (current < (questions?.length || 1) - 1) {
      setCurrent(current + 1);
    } else {
      submitAnswers([...answers, ...(answer ? [answer] : [])]);
    }
  };

  const choose = (optionId: string) => {
    if (lockedRef.current) return;
    setChosen(optionId);
  };

  const confirmChoice = () => {
    if (lockedRef.current) return;
    lockedRef.current = true;
    const option = currentQuestion?.options.find((candidate) => candidate.id === chosen);
    const custom = option?.requires_custom_text ? customText.trim() || null : null;
    const answer = buildAnswer(chosen, custom);
    if (answer) advance(answer);
  };

  const submitAnswers = async (all: Answer[]) => {
    setSubmitting(true);
    setError('');
    try {
      const updated = await api<InitSession>(`/v1/twin/initializations/${session.id}/social-answers`, 'POST', {
        data: { answers: all },
      });
      onDone(updated);
    } catch (e) {
      setError(e instanceof Error ? e.message : '提交失败，请重试');
      setSubmitting(false);
    }
  };

  // 已完成（续做）时展示摘要。
  if (saved?.answers?.length) {
    const counted = saved.answers.filter((item) => item.status === 'counted').length;
    return (
      <StepCard step={5} total={6} title="情景反应已完成" description={`${counted} 题计入行为记忆，超时作答不会写入画像。`}>
        <div className="space-y-2">
          {saved.answers.map((item) => (
            <div key={item.question_id} className="rounded-xl bg-[#f6f7f8] p-3">
              <p className="text-sm font-medium">{item.scene}</p>
              <p className="mt-1 text-sm text-[#646a73]">
                {item.status === 'counted' ? `你的反应：${item.reaction}` : '本题超时，未计入'}
                {item.elapsed_seconds != null && <span className="ml-2 text-xs text-[#8590a6]">{item.elapsed_seconds}s</span>}
              </p>
            </div>
          ))}
        </div>
        <div className="mt-6 flex items-center justify-between">
          <SecondaryButton onClick={onBack}>上一步</SecondaryButton>
          <PrimaryButton onClick={() => onDone(session)}>下一步</PrimaryButton>
        </div>
      </StepCard>
    );
  }

  if (!questions) {
    return (
      <StepCard step={5} total={6} title="现实社交情景">
        <ErrorBanner message={error} />
        <LoadingBlock text="正在准备社交情景题…" />
      </StepCard>
    );
  }

  if (questions.length === 0) {
    return (
      <StepCard step={5} total={6} title="现实社交情景">
        <p className="text-sm text-[#646a73]">暂时没有可用的情景题，请稍后重试或跳到下一步。</p>
        <div className="mt-6 flex items-center justify-between">
          <SecondaryButton onClick={onBack}>上一步</SecondaryButton>
          <PrimaryButton onClick={() => onDone(session)}>跳过此步</PrimaryButton>
        </div>
      </StepCard>
    );
  }

  const chosenOption = currentQuestion?.options.find((option) => option.id === chosen);
  const needsCustom = !!chosenOption?.requires_custom_text;
  const percent = Math.max(0, Math.min(100, (remaining / limit) * 100));
  const answeredCount = answers.length;

  return (
    <StepCard
      step={5}
      total={6}
      title="现实社交情景"
      description={`凭第一反应作答，每题限时 ${limit} 秒。你的下意识反应会写入数字分身的行为记忆，超时的作答不会计入。`}
    >
      <div className="mb-4 flex items-center justify-between text-xs text-[#8590a6]">
        <span>
          第 {current + 1} / {questions.length} 题 · 已完成 {answeredCount}
        </span>
        <span className={'flex items-center gap-1 font-medium ' + (remaining <= 3 ? 'text-[#c45656]' : 'text-[#0084ff]')}>
          <Timer size={13} />
          {remaining.toFixed(1)}s
        </span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-[#eef0f2]">
        <div
          className={'h-full rounded-full transition-all duration-100 ' + (remaining <= 3 ? 'bg-[#e05252]' : 'bg-[#0084ff]')}
          style={{ width: `${percent}%` }}
        />
      </div>

      {currentQuestion && (
        <>
          <p className="mt-5 rounded-xl bg-[#f6f7f8] p-4 text-base leading-8">{currentQuestion.scene}</p>
          {timedOut ? (
            <div className="mt-4 rounded-xl border border-[#fde2e2] bg-[#fef1f1] p-4 text-sm text-[#c45656]">
              本题超时，未计入行为记忆。
              <button
                onClick={() => advance(buildAnswer(null, null))}
                className="ml-2 font-medium underline underline-offset-2"
              >
                下一题
              </button>
            </div>
          ) : (
            <div className="mt-4 space-y-2">
              {currentQuestion.options.map((option) => (
                <div key={option.id}>
                  <OptionRow label={option.label} selected={chosen === option.id} onClick={() => choose(option.id)} />
                  {chosen === option.id && option.requires_custom_text && (
                    <div className="mt-2 flex gap-2">
                      <input
                        value={customText}
                        onChange={(event) => setCustomText(event.target.value)}
                        placeholder="你的真实反应（选填）"
                        maxLength={120}
                        className="flex-1 rounded-xl border border-[#c9dcf2] bg-[#fafcff] px-3 py-2 text-sm outline-none focus:border-[#0084ff]"
                      />
                      <button
                        onClick={confirmChoice}
                        className="shrink-0 rounded-xl bg-[#0084ff] px-4 text-sm font-medium text-white"
                      >
                        确认
                      </button>
                    </div>
                  )}
                </div>
              ))}
              {!needsCustom && chosen && (
                <button
                  onClick={confirmChoice}
                  className="mt-1 w-full rounded-xl bg-[#0084ff] py-2.5 text-sm font-medium text-white"
                >
                  确认选择
                </button>
              )}
            </div>
          )}
        </>
      )}

      <ErrorBanner message={error} />
      <div className="mt-6 flex items-center justify-between">
        <span className="text-xs text-[#8590a6]">提交后开始计时，无法回看修改</span>
        {submitting && <span className="text-sm text-[#8590a6]">正在保存…</span>}
      </div>
    </StepCard>
  );
}
