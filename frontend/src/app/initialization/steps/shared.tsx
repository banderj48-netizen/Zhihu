// 初始化向导各步骤共用的小组件与工具。
'use client';

import type { ReactNode } from 'react';
import { AlertCircle, ArrowLeft, ArrowRight } from 'lucide-react';
import type { DomainNode, InitSession, MePayload } from '../../../lib/api';

/** 六个步骤组件统一的属性。 */
export type StepProps = {
  session: InitSession;
  me: MePayload;
  catalog: DomainNode[];
  onDone: (updated: InitSession) => void;
  onBack: () => void;
};

/** 步骤内容卡：白卡 + 步骤序号标签 + 标题 + 说明。 */
export function StepCard({
  step,
  total,
  title,
  description,
  children,
}: {
  step: number;
  total: number;
  title: string;
  description?: string;
  children: ReactNode;
}) {
  return (
    <section className="rounded-2xl border border-[#ebebeb] bg-white p-6 shadow-sm sm:p-8">
      <p className="text-xs font-medium text-[#0084ff]">
        第 {step} / {total} 步
      </p>
      <h1 className="mt-2 text-2xl font-semibold">{title}</h1>
      {description && <p className="mt-2 text-sm leading-6 text-[#646a73]">{description}</p>}
      <div className="mt-6">{children}</div>
    </section>
  );
}

/** 主按钮（下一步/提交）。 */
export function PrimaryButton({
  children,
  onClick,
  disabled,
  loading,
}: {
  children: ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  loading?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled || loading}
      className="flex items-center justify-center gap-2 rounded-md bg-[#0084ff] px-5 py-2.5 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-60"
    >
      {loading ? '处理中…' : children}
      {!loading && <ArrowRight size={15} />}
    </button>
  );
}

/** 次按钮（上一步/跳过等）。 */
export function SecondaryButton({
  children,
  onClick,
  disabled,
}: {
  children: ReactNode;
  onClick?: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className="flex items-center gap-1.5 rounded-md border border-[#e3e6e8] bg-white px-4 py-2.5 text-sm text-[#646a73] hover:bg-[#f6f6f6] disabled:cursor-not-allowed disabled:opacity-60"
    >
      <ArrowLeft size={14} />
      {children}
    </button>
  );
}

/** 文字按钮（跳过、重新选择等轻量操作）。 */
export function TextButton({ children, onClick }: { children: ReactNode; onClick?: () => void }) {
  return (
    <button onClick={onClick} className="text-sm text-[#8590a6] underline-offset-2 hover:text-[#0084ff] hover:underline">
      {children}
    </button>
  );
}

/** 错误提示条。 */
export function ErrorBanner({ message }: { message: string }) {
  if (!message) return null;
  return (
    <div className="flex items-start gap-2 rounded-lg border border-[#fde2e2] bg-[#fef1f1] p-3 text-sm text-[#c45656]">
      <AlertCircle size={16} className="mt-0.5 shrink-0" />
      <span>{message}</span>
    </div>
  );
}

/** 加载占位。 */
export function LoadingBlock({ text = '加载中…' }: { text?: string }) {
  return <div className="py-10 text-center text-sm text-[#8590a6]">{text}</div>;
}

/** 单选项行（观点题/情景题共用）。 */
export function OptionRow({
  label,
  selected,
  onClick,
}: {
  label: string;
  selected: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={
        'flex w-full items-center gap-3 rounded-xl border p-4 text-left text-sm leading-6 transition ' +
        (selected
          ? 'border-[#0084ff] bg-[#f0f7ff] text-[#235b91] shadow-[0_0_0_3px_rgba(0,132,255,.10)]'
          : 'border-[#e3e6e8] bg-white hover:border-[#c9dcf2] hover:bg-[#fafcff]')
      }
    >
      <span
        className={
          'flex h-4 w-4 shrink-0 items-center justify-center rounded-full border ' +
          (selected ? 'border-[#0084ff]' : 'border-[#c9cdd4]')
        }
      >
        {selected && <span className="h-2 w-2 rounded-full bg-[#0084ff]" />}
      </span>
      <span>{label}</span>
    </button>
  );
}

/** 截断显示，避免长 ID 撑破布局。 */
export function shortId(value: string | null | undefined) {
  if (!value) return '-';
  return value.length > 12 ? `${value.slice(0, 8)}…${value.slice(-4)}` : value;
}
