// 第 1 步：导入知乎资料。
// 已连接知乎时列出真实创作内容供勾选，同时启动后端导入任务并轮询进度；
// 未连接知乎时仅运行模拟导入。所选清单会作为快照存入初始化会话留档。
'use client';

import { useEffect, useRef, useState } from 'react';
import { FileText, ThumbsUp } from 'lucide-react';
import { api, apiEnvelope, type ContentItem, type InitSession } from '../../../lib/api';
import { ErrorBanner, LoadingBlock, PrimaryButton, SecondaryButton, StepCard, TextButton, type StepProps } from './shared';

const CONTENT_TYPE_LABEL: Record<string, string> = {
  answer: '回答',
  article: '文章',
  zvideo: '视频',
  pin: '想法',
  question: '提问',
};

export default function ImportStep({ session, me, onDone, onBack }: StepProps) {
  const [contents, setContents] = useState<ContentItem[] | null>(null);
  const [loadError, setLoadError] = useState('');
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState<{ status: string; progress: number; message: string } | null>(null);
  const [error, setError] = useState('');
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    (async () => {
      if (!me.zhihu_connected) {
        setContents([]);
        return;
      }
      try {
        const payload = await apiEnvelope<{ items: ContentItem[] }>(
          '/api/v1/zhihu/contents?type=all&limit=50'
        );
        const items = payload?.items || [];
        setContents(items);
        // 默认全选（最多 20 条），用户可自行取消。
        setSelected(new Set(items.slice(0, 20).map((_, index) => index)));
      } catch (e) {
        setLoadError(e instanceof Error ? e.message : '知乎资料读取失败');
        setContents([]);
      }
    })();
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [me.zhihu_connected]);

  const toggle = (index: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });
  };

  const finishStep = async (payload: Record<string, unknown>) => {
    const updated = await api<InitSession>(
      `/v1/twin/initializations/${session.id}/zhihu-import`,
      'POST',
      { data: payload }
    );
    onDone(updated);
  };

  const runImport = async () => {
    setRunning(true);
    setError('');
    try {
      // 启动导入任务并轮询进度，直到 completed。
      const job = await api<{ id: string }>('/v1/import-jobs', 'POST', {
        consent_id: `consent_${me.user_id}`,
        source: 'zhihu',
        options: { initialize_agent: true },
      });
      const finalJob = await new Promise<{ status: string; progress: number; message: string }>((resolve, reject) => {
        timerRef.current = setInterval(async () => {
          try {
            const task = await api<{ status: string; progress: number; message: string }>(
              `/v1/import-jobs/${job.id}`
            );
            setProgress(task);
            if (task.status === 'completed' || task.status === 'failed') {
              if (timerRef.current) clearInterval(timerRef.current);
              resolve(task);
            }
          } catch (e) {
            if (timerRef.current) clearInterval(timerRef.current);
            reject(e);
          }
        }, 700);
      });
      if (finalJob.status === 'failed') throw new Error('导入任务失败，请重试');
      const picked = (contents || []).filter((_, index) => selected.has(index));
      await finishStep({
        job_id: job.id,
        imported_count: picked.length,
        zhihu_connected: me.zhihu_connected,
        selected: picked.map((item) => ({
          title: item.title,
          url: item.url,
          content_type: item.content_type,
          like_count: item.like_count,
        })),
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : '导入失败，请重试');
      setRunning(false);
    }
  };

  const skip = async () => {
    setRunning(true);
    try {
      await finishStep({ skipped: true, zhihu_connected: me.zhihu_connected, selected: [] });
    } catch (e) {
      setError(e instanceof Error ? e.message : '操作失败，请重试');
      setRunning(false);
    }
  };

  return (
    <>
      <StepCard
        step={1}
        total={6}
        title="导入知乎资料"
        description="你的知乎回答和帖子将用于提炼专长、兴趣、观点和行为记忆。也可以选择跳过，稍后手动补充。"
      >
        {contents === null ? (
          <LoadingBlock text="正在读取你的知乎创作…" />
        ) : (
          <>
            <ErrorBanner message={loadError} />
            {contents.length > 0 ? (
              <div className="max-h-80 space-y-2 overflow-y-auto pr-1">
                {contents.map((item, index) => {
                  const checked = selected.has(index);
                  return (
                    <button
                      key={`${item.url}-${index}`}
                      onClick={() => toggle(index)}
                      className={
                        'flex w-full items-start gap-3 rounded-xl border p-3 text-left transition ' +
                        (checked ? 'border-[#0084ff] bg-[#f0f7ff]' : 'border-[#e3e6e8] bg-white hover:bg-[#fafcff]')
                      }
                    >
                      <span
                        className={
                          'mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded border ' +
                          (checked ? 'border-[#0084ff] bg-[#0084ff]' : 'border-[#c9cdd4]')
                        }
                      >
                        {checked && (
                          <svg viewBox="0 0 10 8" className="h-2.5 w-2.5 fill-none stroke-white stroke-[2]">
                            <path d="M1 4l2.5 2.5L9 1" />
                          </svg>
                        )}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="flex items-center gap-2">
                          <FileText size={14} className="shrink-0 text-[#8590a6]" />
                          <span className="truncate text-sm font-medium">{item.title || '(无标题)'}</span>
                          <span className="shrink-0 rounded bg-[#f0f2f4] px-1.5 py-0.5 text-[11px] text-[#646a73]">
                            {CONTENT_TYPE_LABEL[item.content_type] || item.content_type}
                          </span>
                        </span>
                        {item.like_count != null && item.like_count > 0 && (
                          <span className="mt-1 flex items-center gap-1 text-xs text-[#8590a6]">
                            <ThumbsUp size={11} />
                            {item.like_count} 赞同
                          </span>
                        )}
                      </span>
                    </button>
                  );
                })}
              </div>
            ) : (
              <div className="rounded-xl bg-[#f6f7f8] p-4 text-sm leading-6 text-[#646a73]">
                {me.zhihu_connected
                  ? '没有读取到可导入的知乎内容，可以直接继续。'
                  : '当前未连接知乎创作数据，将使用演示导入流程完成这一步。'}
              </div>
            )}

            {progress && (
              <div className="mt-5">
                <div className="mb-1.5 flex items-center justify-between text-xs text-[#646a73]">
                  <span>{progress.message}</span>
                  <span>{progress.progress}%</span>
                </div>
                <div className="h-2 overflow-hidden rounded-full bg-[#eef0f2]">
                  <div
                    className="h-full rounded-full bg-[#0084ff] transition-all duration-500"
                    style={{ width: `${progress.progress}%` }}
                  />
                </div>
              </div>
            )}

            <ErrorBanner message={error} />
            <div className="mt-6 flex flex-wrap items-center justify-between gap-3">
              <SecondaryButton onClick={onBack}>上一步</SecondaryButton>
              <div className="flex items-center gap-4">
                <TextButton onClick={skip}>跳过导入</TextButton>
                <PrimaryButton onClick={runImport} loading={running}>
                  {progress ? '正在导入…' : `导入所选内容${contents.length ? `（${selected.size} 条）` : ''}`}
                </PrimaryButton>
              </div>
            </div>
          </>
        )}
      </StepCard>
    </>
  );
}
