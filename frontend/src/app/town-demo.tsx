'use client';

import { useState } from 'react';
import { ArrowLeft, ArrowRight, MapPin, MessageCircle, Sparkles, Users } from 'lucide-react';

type Scene = { id: string; name: string; image: string; position: string; tint: string; };
type Candidate = { id: string; name: string; image: string; intro: string; topic: string; };

const scenes: Scene[] = [
  { id: 'cafe', name: '咖啡馆', image: '/scenes/咖啡馆.png', position: 'left-[62%] top-[8%]', tint: 'bg-[#e9f3ff]' },
  { id: 'library', name: '图书馆', image: '/scenes/图书馆.png', position: 'left-[2%] top-[29%]', tint: 'bg-[#f8efdf]' },
  { id: 'bar', name: '小酒馆', image: '/scenes/小酒馆.png', position: 'left-[80%] top-[28%]', tint: 'bg-[#eee9f8]' },
  { id: 'theater', name: '戏剧院', image: '/scenes/戏剧院.jpg', position: 'left-[8%] top-[57%]', tint: 'bg-[#f7e9ec]' },
  { id: 'lecture', name: '讲座', image: '/scenes/讲座.jpg', position: 'left-[38%] top-[58%]', tint: 'bg-[#e7f4f4]' },
];

const candidateSets: Record<string, Candidate[]> = {
  cafe: [
    { id: 'c1', name: '小雨', image: '/scenes/female-kanshan.png', intro: '喜欢观察城市里的小细节', topic: '第一次拿起相机时在看什么' },
    { id: 'c2', name: '小周', image: '/scenes/male-kanshan.png', intro: '最近在研究咖啡和人的关系', topic: '一杯咖啡适合聊什么' },
  ],
  library: [
    { id: 'l1', name: '小陈', image: '/scenes/male-kanshan.png', intro: '习惯在窗边整理阅读清单', topic: '如何建立不被打扰的阅读时间' },
    { id: 'l2', name: '小林', image: '/scenes/female-kanshan.png', intro: '最近在读关于城市的书', topic: '一本书怎样改变对一座城的理解' },
    { id: 'l3', name: '小顾', image: '/scenes/male-kanshan.png', intro: '喜欢把复杂问题拆开慢慢想', topic: '读完一本书之后还会留下什么' },
  ],
  bar: [
    { id: 'b1', name: '小许', image: '/scenes/male-kanshan.png', intro: '对技术和故事都保持好奇', topic: '技术会不会改变我们讲故事的方式' },
  ],
  theater: [
    { id: 't1', name: '小许', image: '/scenes/female-kanshan.png', intro: '喜欢从人物和感受出发聊天', topic: '一个角色为什么会让人记住' },
    { id: 't2', name: '小唐', image: '/scenes/male-kanshan.png', intro: '偶尔写一些短剧本', topic: '舞台上的停顿有什么意义' },
  ],
  lecture: [
    { id: 'g1', name: '小许', image: '/scenes/male-kanshan.png', intro: '关注技术如何影响普通人的生活', topic: '技术会不会改变我们讲故事的方式' },
    { id: 'g2', name: '小叶', image: '/scenes/female-kanshan.png', intro: '喜欢把观点讲清楚再继续追问', topic: '一个好问题从哪里开始' },
    { id: 'g3', name: '小吴', image: '/scenes/male-kanshan.png', intro: '正在寻找新的研究方向', topic: '我们为什么需要持续学习' },
  ],
};

function MyKanshan() {
  return <div className="rounded-2xl border border-[#cfe6fb] bg-[#f0f7ff] p-5"><div className="flex items-center gap-3"><div className="h-16 w-16 overflow-hidden rounded-full bg-white"><img src="/scenes/female-kanshan.png" alt="我的看山" className="h-full w-full object-contain" /></div><div><p className="text-sm font-semibold text-[#235b91]">我的看山</p><p className="mt-1 text-xs leading-5 text-[#5d7184]">正在左边观察场景，帮你发现可能聊得来的人。</p></div></div><div className="mt-4 rounded-xl bg-white/80 p-3 text-sm leading-6 text-[#3f566a]">我会先听完一段对话，再把共同话题、可能的差异和适合继续聊的方向告诉你。</div></div>;
}

function SceneRoom({ scene, onBack }: { scene: Scene; onBack: () => void }) {
  const candidates = candidateSets[scene.id] ?? [];
  const [selected, setSelected] = useState<Candidate | null>(null);
  const [hovered, setHovered] = useState<string | null>(null);
  return <div><button onClick={onBack} className="mb-5 flex items-center gap-2 text-sm text-[#646a73] hover:text-[#0084ff]"><ArrowLeft size={16} />返回小镇</button><div className="mb-6 flex items-end justify-between gap-4"><div><div className="mb-2 flex items-center gap-2 text-sm font-medium text-[#0084ff]"><MapPin size={16} />{scene.name}</div><h1 className="text-3xl font-semibold">在{scene.name}里，看看谁正在聊天</h1><p className="mt-2 text-[#646a73]">我的看山在左边，可能遇见的人在右边。把鼠标移到头像上，看看他们最近在想什么。</p></div><div className="rounded-lg border border-[#ebebeb] bg-white px-3 py-2 text-xs text-[#8590a6]"><Users size={14} className="mr-1 inline" />{candidates.length} 位可能遇见的人</div></div><div className="relative min-h-[620px] overflow-hidden rounded-2xl border border-[#e3e6e8] bg-[#25322c] shadow-xl"><img src={scene.image} alt={scene.name+'场景'} className="absolute inset-0 h-full w-full object-cover" /><div className="absolute inset-0 bg-gradient-to-r from-[#13251f]/65 via-transparent to-[#13251f]/35" /><div className="absolute left-5 top-5 rounded-full bg-white/90 px-3 py-1.5 text-xs text-[#4d6259] shadow-sm"><MapPin size={13} className="mr-1 inline text-[#0084ff]" />{scene.name}</div><div className="absolute bottom-6 left-[8%] z-10 flex w-40 flex-col items-center transition-all duration-700" style={{ transform: selected ? 'translateX(180%)' : 'translateX(0)' }}><div className="relative h-52 w-32"><img src="/scenes/female-kanshan.png" alt="我的看山" className="h-full w-full object-contain drop-shadow-[0_12px_8px_rgba(0,0,0,.35)]" /><span className="absolute -top-2 left-1/2 -translate-x-1/2 whitespace-nowrap rounded-full bg-white/95 px-3 py-1 text-xs font-medium text-[#e86f51] shadow-sm">我的看山</span></div><p className="mt-1 rounded-full bg-black/35 px-3 py-1 text-xs text-white">{selected ? '正在和 '+selected.name+' 聊天' : '在左边观察'}</p></div>{candidates.map((candidate,index) => { const isSelected = selected?.id === candidate.id; const pos = index===0 ? 'right-[27%] bottom-[15%]' : index===1 ? 'right-[12%] bottom-[21%]' : 'right-[40%] bottom-[9%]'; return <div key={candidate.id} className={'absolute z-10 '+pos}><button onMouseEnter={()=>setHovered(candidate.id)} onMouseLeave={()=>setHovered(null)} onFocus={()=>setHovered(candidate.id)} onBlur={()=>setHovered(null)} onClick={()=>setSelected(candidate)} className={'relative h-48 w-32 transition-all duration-700 '+(isSelected?'scale-110':'hover:scale-105')} style={isSelected ? { transform: 'translateX(-180px)' } : undefined}><img src={candidate.image} alt={candidate.name} className="h-full w-full object-contain drop-shadow-[0_12px_8px_rgba(0,0,0,.4)]" /><span className="absolute -bottom-1 left-1/2 h-3 w-3 -translate-x-1/2 rounded-full bg-[#0084ff] shadow-[0_0_0_5px_rgba(0,132,255,.22)]" /><span className="absolute -top-2 left-1/2 -translate-x-1/2 whitespace-nowrap rounded-full bg-white/90 px-2.5 py-1 text-xs font-medium text-[#235b91] shadow-sm">{candidate.name}</span>{hovered===candidate.id&&!isSelected&&<span className="absolute bottom-[92%] left-1/2 z-20 w-52 -translate-x-1/2 rounded-xl border border-white/70 bg-white p-3 text-left shadow-2xl"><span className="block text-xs font-semibold text-[#1a1a1a]">看山 · {candidate.name}</span><span className="mt-1 block text-[11px] leading-5 text-[#646a73]">{candidate.intro}</span><span className="mt-2 block text-[11px] leading-5 text-[#8590a6]">可能聊到：{candidate.topic}</span></span>}</button></div>})}<div className="absolute bottom-5 left-1/2 z-20 -translate-x-1/2 rounded-full bg-white/90 px-4 py-2 text-xs text-[#4d6259] shadow-lg">{selected ? '看山正在交换想法 · 点击其他头像可切换' : '点击右侧看山，让我的看山走过去聊天'}</div></div></div>;
}

export default function TownDemo() {
  const [scene, setScene] = useState<Scene | null>(null);
  if (scene) return <SceneRoom scene={scene} onBack={() => setScene(null)} />;
  return <div><div className="mb-7 flex items-end justify-between gap-4"><div><p className="mb-2 text-sm font-medium text-[#0084ff]">小镇漫游 · 昨天</p><h1 className="text-3xl font-semibold tracking-tight">在小镇里，遇见日常的新鲜想法</h1><p className="mt-2 text-[#646a73]">地图素材会持续更新。点击五个建筑，进入对应的场景。</p></div><div className="hidden rounded-lg border border-[#ebebeb] bg-white px-4 py-3 text-right text-xs text-[#8590a6] sm:block"><p>今日开放</p><p className="mt-1 font-medium text-[#1a1a1a]">5 个互动场景</p></div></div><div className="rounded-2xl border border-[#e3e6e8] bg-white p-3 shadow-sm sm:p-4"><div className="mb-3 flex items-center justify-between px-1"><div className="flex items-center gap-2 text-sm font-medium"><span className="flex h-7 w-7 items-center justify-center rounded-full bg-[#e6f3ff] text-[#0084ff]"><MapPin size={14} /></span>Sunnyvale 小镇</div><div className="flex items-center gap-2 text-xs text-[#8590a6]"><span className="h-2 w-2 animate-pulse rounded-full bg-[#31b27a]" />漫游中 · 5 个场景</div></div><div className="relative overflow-hidden rounded-xl bg-[#f2eee8]"><img src="/town/townmap.jpg" alt="Sunnyvale 小镇地图" className="block aspect-[1348/960] h-full w-full object-cover" />{scenes.map((item) => <button key={item.id} onClick={() => setScene(item)} className={'group absolute '+item.position+' h-[22%] w-[21%] rounded-2xl border-2 border-transparent transition hover:border-[#0084ff] hover:bg-[#0084ff]/10 focus:outline-none focus-visible:ring-4 focus-visible:ring-[#0084ff]/35'} aria-label={'进入'+item.name}><span className={'absolute bottom-2 left-1/2 flex -translate-x-1/2 items-center gap-1 whitespace-nowrap rounded-full px-2.5 py-1 text-[11px] font-medium text-[#235b91] opacity-0 shadow-md transition group-hover:opacity-100 '+item.tint}><MapPin size={12} />{item.name}</span><span className="absolute bottom-[14%] left-1/2 h-3 w-3 -translate-x-1/2 rounded-full bg-[#0084ff] shadow-[0_0_0_6px_rgba(0,132,255,.16)] transition group-hover:scale-125" /></button>)}</div></div><div className="mt-4 flex items-center gap-2 text-xs text-[#8590a6]"><Sparkles size={14} className="text-[#0084ff]" />五个建筑入口已经放在地图上，点击即可进入场景。</div></div>;
}


