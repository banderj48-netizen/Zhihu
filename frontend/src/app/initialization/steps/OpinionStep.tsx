// 第 4 步：领域观点选择题。
// 题目由后端按已选领域生成（LLM 结合知乎讨论动态出题，未配置时回退内置题库），
// 每题 3-5 个平衡立场 + 自定义选项；答案会写入观点记忆的来源材料。
'use client';

import { useEffect, useMemo, useState } from 'react';
import { api, type InitSession } from '../../../lib/api';
import { ErrorBanner, LoadingBlock, OptionRow, PrimaryButton, SecondaryButton, StepCard, type StepProps } from './shared';

type Option = { id: string; label: string; requires_custom_text?: boolean; scoring?: string };
type Question = {
  question_id: string;
  question_version: number;
  domain_id: string;
  question_type: string;
  prompt: string;
  options: Option[];
};
type SavedAnswers = { answers?: AnswerRecord[] };
type AnswerRecord = {
  question_id: string;
  question_version: number;
  domain_id: string;
  topic: string;
  prompt: string;
  level: string;
  selected_option_id: string | null;
  custom_text: string | null;
  content: string;
};

export default function OpinionStep({ session, catalog, onDone, onBack }: StepProps) {
  const saved = session.input_data?.['opinion-answers'] as SavedAnswers | undefined;
  const [questions, setQuestions] = useState<Question[] | null>(null);
  const [current, setCurrent] = useState(0);
  const [selected, setSelected] = useState<Record<string, string>>({});
  const [customText, setCustomText] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  const labelOf = useMemo(() => {
    const map = new Map(catalog.map((node) => [node.id, node.label]));
    return (id: string) => map.get(id) || id;
  }, [catalog]);

  useEffect(() => {
    if (saved?.answers?.length) {
      setQuestions([]);
      return;
    }
    const domains = session.input_data?.domains;
    const domainIds: string[] = [
      ...((domains?.interests as { domain_id: string }[] | undefined) || []),
      ...((domains?.expertise as { domain_id: string }[] | undefined) || []),
    ].map((item) => item.domain_id);
    api<{ questions: Question[] }>(`/v1/twin/initializations/${session.id}/opinion-questions`, 'POST', {
      count: 5,
      domain_ids: domainIds,
    })
      .then((payload) => setQuestions(payload.questions || []))
      .catch((e) => setError(e instanceof Error ? e.message : '题目生成失败'));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 已完成（续做）时展示当时的作答摘要。
  if (saved?.answers?.length) {
    return (
      <StepCard step={4} total={6} title="观点问答已完成" description="以下观点已写入画像素材，进入下一步。">
        <div className="space-y-2">
          {saved.answers.map((answer) => (
            <div key={answer.question_id} className="rounded-xl bg-[#f6f7f8] p-3">
              <p className="text-sm font-medium">{answer.prompt}</p>
              <p className="mt-1 text-sm text-[#646a73]">你的选择：{answer.content}</p>
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
      <StepCard step={4} total={6} title="领域观点问答">
        <ErrorBanner message={error} />
        <LoadingBlock text="正在根据你选择的领域生成观点题…" />
      </StepCard>
    );
  }

  if (questions.length === 0) {
    return (
      <StepCard step={4} total={6} title="领域观点问答">
        <p className="text-sm text-[#646a73]">暂时没有可生成的题目，请返回上一步确认已选择领域。</p>
        <div className="mt-6">
          <SecondaryButton onClick={onBack}>返回领域选择</SecondaryButton>
        </div>
      </StepCard>
    );
  }

  const question = questions[current];
  const optionOf = (id: string | null) => question.options.find((option) => option.id === id);
  const chosen = selected[question.question_id] || '';
  const chosenOption = optionOf(chosen);
  const needsCustom = !!chosenOption?.requires_custom_text;
  const canAdvance = chosen && (!needsCustom || customText[question.question_id]?.trim().length > 0);

  const recordAnswer = (optionId: string) => {
    setSelected((prev) => ({ ...prev, [question.question_id]: optionId }));
  };

  const next = async () => {
    if (current < questions.length - 1) {
      setCurrent(current + 1);
      return;
    }
    setSubmitting(true);
    setError('');
    try {
      const answers: AnswerRecord[] = questions.map((item) => {
        const optionId = selected[item.question_id] || null;
        const option = item.options.find((candidate) => candidate.id === optionId);
        const custom = customText[item.question_id]?.trim() || null;
        return {
          question_id: item.question_id,
          question_version: item.question_version,
          domain_id: item.domain_id,
          topic: labelOf(item.domain_id),
          prompt: item.prompt,
          level: 'middle',
          selected_option_id: optionId,
          custom_text: custom,
          // content 是画像记忆的默认文案：自定义答案优先，否则用选项原文。
          content: custom || option?.label || (optionId ? `选择选项 ${optionId}` : ''),
        };
      });
      const updated = await api<InitSession>(`/v1/twin/initializations/${session.id}/opinion-answers`, 'POST', {
        data: { answers },
      });
      onDone(updated);
    } catch (e) {
      setError(e instanceof Error ? e.message : '提交失败，请重试');
      setSubmitting(false);
    }
  };

  return (
    <StepCard
      step={4}
      total={6}
      title="领域观点问答"
      description="这些题来自你选择领域的真实讨论，没有对错。你的立场和判断标准会成为数字分身的观点画像。"
    >
      <div className="mb-4 flex items-center justify-between text-xs text-[#8590a6]">
        <span>
          第 {current + 1} / {questions.length} 题
        </span>
        <span className="rounded bg-[#f0f2f4] px-2 py-0.5">{labelOf(question.domain_id)}</span>
      </div>
      <div className="mb-2 h-1.5 overflow-hidden rounded-full bg-[#eef0f2]">
        <div
          className="h-full rounded-full bg-[#0084ff] transition-all"
          style={{ width: `${((current + 1) / questions.length) * 100}%` }}
        />
      </div>
      <p className="mt-5 text-lg font-medium leading-8">{question.prompt}</p>
      <div className="mt-4 space-y-2">
        {question.options.map((option) => (
          <div key={option.id}>
            <OptionRow label={option.label} selected={chosen === option.id} onClick={() => recordAnswer(option.id)} />
            {chosen === option.id && option.requires_custom_text && (
              <textarea
                value={customText[question.question_id] || ''}
                onChange={(event) => setCustomText((prev) => ({ ...prev, [question.question_id]: event.target.value }))}
                placeholder="说说你的具体看法（必填）"
                rows={3}
                maxLength={300}
                className="mt-2 w-full rounded-xl border border-[#c9dcf2] bg-[#fafcff] p-3 text-sm outline-none focus:border-[#0084ff]"
              />
            )}
          </div>
        ))}
      </div>
      <ErrorBanner message={error} />
      <div className="mt-6 flex items-center justify-between">
        {current > 0 ? (
          <SecondaryButton onClick={() => setCurrent(current - 1)}>上一题</SecondaryButton>
        ) : (
          <SecondaryButton onClick={onBack}>上一步</SecondaryButton>
        )}
        <PrimaryButton onClick={next} disabled={!canAdvance} loading={submitting}>
          {current < questions.length - 1 ? '下一题' : '提交观点问答'}
        </PrimaryButton>
      </div>
    </StepCard>
  );
}
