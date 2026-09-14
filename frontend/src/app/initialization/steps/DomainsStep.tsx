// 第 3 步：选择兴趣与擅长领域。
// 领域目录是 根域 -> 分类 -> 叶子 三级，只有叶子可选。
// 兴趣带 1-3 强度，擅长带自评熟练度；提交时写入领域选择表（乐观锁）与初始化会话。
'use client';

import { useEffect, useMemo, useState } from 'react';
import { ChevronDown, Search, X } from 'lucide-react';
import { api, type InitSession } from '../../../lib/api';
import { ErrorBanner, PrimaryButton, SecondaryButton, StepCard, type StepProps } from './shared';

type DomainSel = { domain_id: string; interest_level?: number; proficiency?: string; notes?: string };
type SavedDomains = { interests?: DomainSel[]; expertise?: DomainSel[] };

const INTEREST_LEVELS: [number, string][] = [
  [1, '一般'],
  [2, '较浓'],
  [3, '热爱'],
];
const PROFICIENCIES: [string, string][] = [
  ['novice', '入门'],
  ['familiar', '熟悉'],
  ['working', '熟练'],
  ['advanced', '精通'],
];

export default function DomainsStep({ session, catalog, onDone, onBack }: StepProps) {
  const saved = session.input_data?.domains as SavedDomains | undefined;
  const [tab, setTab] = useState<'interests' | 'expertise'>('interests');
  const [interests, setInterests] = useState<Record<string, number>>(() =>
    Object.fromEntries((saved?.interests || []).map((item) => [item.domain_id, item.interest_level ?? 2]))
  );
  const [expertise, setExpertise] = useState<Record<string, string>>(() =>
    Object.fromEntries((saved?.expertise || []).map((item) => [item.domain_id, item.proficiency || 'working']))
  );
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [query, setQuery] = useState('');
  const [revision, setRevision] = useState<number | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    // 读取既有选择以获得 revision；会话里没有已选内容时也顺便恢复历史选择。
    api<{ revision: number; interests: DomainSel[]; expertise: DomainSel[] }>('/v1/domains/selections/me')
      .then((payload) => {
        setRevision(payload.revision ?? 0);
        if (!saved?.interests?.length && !saved?.expertise?.length) {
          setInterests(Object.fromEntries((payload.interests || []).map((item) => [item.domain_id, item.interest_level ?? 2])));
          setExpertise(Object.fromEntries((payload.expertise || []).map((item) => [item.domain_id, item.proficiency || 'working'])));
        }
      })
      .catch(() => setRevision(0));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const labelOf = useMemo(() => {
    const map = new Map(catalog.map((node) => [node.id, node.label]));
    return (id: string) => map.get(id) || id;
  }, [catalog]);

  const tree = useMemo(() => {
    const roots = catalog.filter((node) => node.level === 'root');
    const categories = catalog.filter((node) => node.level === 'category');
    const leaves = catalog.filter((node) => node.level === 'leaf');
    const leavesByCategory = new Map<string, typeof leaves>();
    for (const leaf of leaves) {
      const list = leavesByCategory.get(leaf.parent_id || '') || [];
      list.push(leaf);
      leavesByCategory.set(leaf.parent_id || '', list);
    }
    const childrenOf = new Map<string, typeof categories>();
    for (const category of categories) {
      const list = childrenOf.get(category.parent_id || '') || [];
      list.push(category);
      childrenOf.set(category.parent_id || '', list);
    }
    return roots.map((root) => ({
      root,
      categories: (childrenOf.get(root.id) || []).map((category) => ({
        category,
        leaves: leavesByCategory.get(category.id) || [],
      })),
    }));
  }, [catalog]);

  const normalizedQuery = query.trim().toLowerCase();
  const visibleTree = useMemo(() => {
    if (!normalizedQuery) return tree;
    return tree
      .map((branch) => ({
        root: branch.root,
        categories: branch.categories
          .map((group) => ({
            category: group.category,
            leaves: group.leaves.filter((leaf) => leaf.label.toLowerCase().includes(normalizedQuery)),
          }))
          .filter((group) => group.leaves.length > 0),
      }))
      .filter((branch) => branch.categories.length > 0);
  }, [tree, normalizedQuery]);

  const toggleLeaf = (id: string) => {
    if (tab === 'interests') {
      setInterests((prev) => {
        const next = { ...prev };
        if (next[id]) delete next[id];
        else next[id] = 2;
        return next;
      });
    } else {
      setExpertise((prev) => {
        const next = { ...prev };
        if (next[id]) delete next[id];
        else next[id] = 'working';
        return next;
      });
    }
  };

  const currentMap = tab === 'interests' ? interests : expertise;
  const totalSelected = Object.keys(interests).length + Object.keys(expertise).length;

  const submit = async () => {
    setSubmitting(true);
    setError('');
    try {
      const payload = {
        expected_revision: revision ?? 0,
        interests: Object.entries(interests).map(([domain_id, interest_level]) => ({ domain_id, interest_level, notes: '' })),
        expertise: Object.entries(expertise).map(([domain_id, proficiency]) => ({ domain_id, proficiency, notes: '' })),
      };
      try {
        await api('/v1/domains/selections/me', 'PUT', payload);
      } catch (e) {
        // 乐观锁冲突（409）时重读最新 revision 重试一次。
        if (e instanceof Error && e.message.includes('409')) {
          const latest = await api<{ revision: number }>('/v1/domains/selections/me');
          await api('/v1/domains/selections/me', 'PUT', { ...payload, expected_revision: latest.revision ?? 0 });
        } else {
          throw e;
        }
      }
      const data = { interests: payload.interests, expertise: payload.expertise };
      const updated = await api<InitSession>(`/v1/twin/initializations/${session.id}/domains`, 'POST', { data });
      onDone(updated);
    } catch (e) {
      setError(e instanceof Error ? e.message : '保存失败，请重试');
      setSubmitting(false);
    }
  };

  return (
    <StepCard
      step={3}
      total={6}
      title="选择兴趣与擅长领域"
      description="你选择的领域会决定接下来的观点题目，也会成为数字分身的兴趣与专长画像。至少选择 1 个。"
    >
      {/* 已选汇总 */}
      <div className="rounded-xl bg-[#f6f7f8] p-4">
        <div className="flex items-center justify-between">
          <p className="text-sm font-medium">已选 {totalSelected} 个领域</p>
          <p className="text-xs text-[#8590a6]">兴趣 {Object.keys(interests).length} · 擅长 {Object.keys(expertise).length}</p>
        </div>
        <div className="mt-3 space-y-2">
          {Object.entries(interests).map(([id, level]) => (
            <div key={`i-${id}`} className="flex items-center justify-between gap-2 rounded-lg bg-white px-3 py-2">
              <span className="truncate text-sm">
                <span className="mr-1.5 text-xs text-[#0084ff]">兴趣</span>
                {labelOf(id)}
              </span>
              <span className="flex shrink-0 items-center gap-1">
                {INTEREST_LEVELS.map(([value, label]) => (
                  <button
                    key={value}
                    onClick={() => setInterests((prev) => ({ ...prev, [id]: value }))}
                    className={
                      'rounded px-2 py-0.5 text-xs ' +
                      (level === value ? 'bg-[#0084ff] text-white' : 'text-[#646a73] hover:bg-[#f0f2f4]')
                    }
                  >
                    {label}
                  </button>
                ))}
                <button onClick={() => setInterests((prev) => { const n = { ...prev }; delete n[id]; return n; })} className="ml-1 text-[#c9cdd4] hover:text-[#c45656]">
                  <X size={14} />
                </button>
              </span>
            </div>
          ))}
          {Object.entries(expertise).map(([id, level]) => (
            <div key={`e-${id}`} className="flex items-center justify-between gap-2 rounded-lg bg-white px-3 py-2">
              <span className="truncate text-sm">
                <span className="mr-1.5 text-xs text-[#9b663d]">擅长</span>
                {labelOf(id)}
              </span>
              <span className="flex shrink-0 items-center gap-1">
                {PROFICIENCIES.map(([value, label]) => (
                  <button
                    key={value}
                    onClick={() => setExpertise((prev) => ({ ...prev, [id]: value }))}
                    className={
                      'rounded px-2 py-0.5 text-xs ' +
                      (level === value ? 'bg-[#9b663d] text-white' : 'text-[#646a73] hover:bg-[#f0f2f4]')
                    }
                  >
                    {label}
                  </button>
                ))}
                <button onClick={() => setExpertise((prev) => { const n = { ...prev }; delete n[id]; return n; })} className="ml-1 text-[#c9cdd4] hover:text-[#c45656]">
                  <X size={14} />
                </button>
              </span>
            </div>
          ))}
          {totalSelected === 0 && <p className="text-xs text-[#8590a6]">还没有选择，从下方目录中挑选吧。</p>}
        </div>
      </div>

      {/* 兴趣 / 擅长切换 */}
      <div className="mt-5 flex items-center gap-2">
        <div className="flex rounded-lg bg-[#f0f2f4] p-1">
          <button
            onClick={() => setTab('interests')}
            className={'rounded-md px-4 py-1.5 text-sm ' + (tab === 'interests' ? 'bg-white font-medium text-[#0084ff] shadow-sm' : 'text-[#646a73]')}
          >
            我感兴趣
          </button>
          <button
            onClick={() => setTab('expertise')}
            className={'rounded-md px-4 py-1.5 text-sm ' + (tab === 'expertise' ? 'bg-white font-medium text-[#9b663d] shadow-sm' : 'text-[#646a73]')}
          >
            我擅长
          </button>
        </div>
        <div className="relative flex-1">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#8590a6]" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索领域，如「心理学」"
            className="w-full rounded-lg border border-[#e3e6e8] bg-white py-2 pl-8 pr-3 text-sm outline-none focus:border-[#0084ff]"
          />
        </div>
      </div>

      {/* 目录手风琴 */}
      <div className="mt-4 max-h-[26rem] space-y-2 overflow-y-auto pr-1">
        {visibleTree.map(({ root, categories }) => {
          const open = expanded.has(root.id) || normalizedQuery.length > 0;
          return (
            <div key={root.id} className="rounded-xl border border-[#ebebeb]">
              <button
                onClick={() =>
                  setExpanded((prev) => {
                    const next = new Set(prev);
                    if (next.has(root.id)) next.delete(root.id);
                    else next.add(root.id);
                    return next;
                  })
                }
                className="flex w-full items-center justify-between px-4 py-3 text-left"
              >
                <span className="text-sm font-medium">{root.label}</span>
                <ChevronDown size={15} className={'text-[#8590a6] transition ' + (open ? 'rotate-180' : '')} />
              </button>
              {open && (
                <div className="space-y-3 border-t border-[#f0f2f4] px-4 py-3">
                  {categories.map(({ category, leaves }) => (
                    <div key={category.id}>
                      <p className="mb-1.5 text-xs text-[#8590a6]">{category.label}</p>
                      <div className="flex flex-wrap gap-1.5">
                        {leaves.map((leaf) => {
                          const active = !!currentMap[leaf.id];
                          return (
                            <button
                              key={leaf.id}
                              onClick={() => toggleLeaf(leaf.id)}
                              className={
                                'rounded-full border px-3 py-1.5 text-xs transition ' +
                                (active
                                  ? tab === 'interests'
                                    ? 'border-[#0084ff] bg-[#e6f3ff] text-[#0084ff]'
                                    : 'border-[#9b663d] bg-[#f7ead8] text-[#9b663d]'
                                  : 'border-[#e3e6e8] bg-white text-[#646a73] hover:border-[#c9dcf2]')
                              }
                            >
                              {leaf.label}
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>

      <ErrorBanner message={error} />
      <div className="mt-6 flex items-center justify-between">
        <SecondaryButton onClick={onBack}>上一步</SecondaryButton>
        <PrimaryButton onClick={submit} disabled={totalSelected === 0} loading={submitting}>
          保存并继续
        </PrimaryButton>
      </div>
    </StepCard>
  );
}
