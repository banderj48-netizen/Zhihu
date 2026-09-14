"""初始化问卷出题服务：领域观点题与现实社交情景题。

观点题按 question-contract.md 契约生成，社交题按 social-question-contract.md
契约生成。优先用 LLM 结合知乎真实讨论素材动态出题；LLM 或知乎素材不可用时
回退到内置模板题库，保证初始化流程始终可以继续。社交情景题的 presented_at
由本模块在服务端打点登记，配合 13 秒限时规则使用。
"""
from __future__ import annotations

import asyncio
import json
import random
import re
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from agent.domains.catalog import BY_ID
from agent.domains.situational import TIME_LIMIT_SECONDS
from agent.adapters.zhihu import search_domain

# ---------------------------------------------------------------------------
# 内置模板题库（LLM 不可用时的兜底；字段含义与契约文档一致）
# ---------------------------------------------------------------------------

_OPINION_BANK: dict[str, list[dict[str, Any]]] = {
    "computer": [
        {"question_type": "applied_tradeoff", "prompt": "团队要把一个核心服务从单体拆成微服务，你更支持哪种推进方式？",
         "options": [
             {"id": "opt_a", "label": "一次性完成拆分，避免长期双轨维护"},
             {"id": "opt_b", "label": "按模块逐步拆分，每步都保留回滚能力"},
             {"id": "opt_c", "label": "先不拆，用规范和测试压住复杂度"},
             {"id": "opt_custom", "label": "其他/自定义答案", "requires_custom_text": True},
             {"id": "opt_unknown", "label": "不知道或暂时无法判断", "scoring": "uncertain"}]},
        {"question_type": "value_priority", "prompt": "代码评审时发现同事的实现能跑但很难维护，你会怎么处理？",
         "options": [
             {"id": "opt_a", "label": "当次放行，之后专门排时间重构"},
             {"id": "opt_b", "label": "本次就要求改到可维护，哪怕延期"},
             {"id": "opt_c", "label": "看改动风险：核心路径必须改，边缘可以放"},
             {"id": "opt_custom", "label": "其他/自定义答案", "requires_custom_text": True}]},
    ],
    "entertainment": [
        {"question_type": "evaluation_standard", "prompt": "评价一款游戏或一部作品时，你更看重什么？",
         "options": [
             {"id": "opt_a", "label": "实际体验和内容完成度，标签和营销不算数"},
             {"id": "opt_b", "label": "作品在题材和表达上的突破性"},
             {"id": "opt_c", "label": "口碑和社区长期评价，自己抽空再验证"},
             {"id": "opt_custom", "label": "其他/自定义答案", "requires_custom_text": True},
             {"id": "opt_unknown", "label": "不知道或暂时无法判断", "scoring": "uncertain"}]},
        {"question_type": "controversy_judgment", "prompt": "面对作品抄袭或剧情争议，你的第一反应是什么？",
         "options": [
             {"id": "opt_a", "label": "先查原文、上下文和可验证证据再下结论"},
             {"id": "opt_b", "label": "参考多方评论快速形成自己的判断"},
             {"id": "opt_c", "label": "争议本身也是作品的一部分，保持观察"},
             {"id": "opt_custom", "label": "其他/自定义答案", "requires_custom_text": True}]},
    ],
    "medicine": [
        {"question_type": "risk_tradeoff", "prompt": "体检出现轻度异常指标但无症状，你倾向于怎么做？",
         "options": [
             {"id": "opt_a", "label": "按周期复查，观察变化趋势"},
             {"id": "opt_b", "label": "尽快做更全面的检查排除风险"},
             {"id": "opt_c", "label": "先调整生活方式，不急于过度检查"},
             {"id": "opt_custom", "label": "其他/自定义答案", "requires_custom_text": True},
             {"id": "opt_unknown", "label": "不知道或暂时无法判断", "scoring": "uncertain"}]},
    ],
    "business": [
        {"question_type": "decision_basis", "prompt": "一个新业务机会信息还不完整，你会依据什么决定是否投入？",
         "options": [
             {"id": "opt_a", "label": "小成本快速验证，用真实反馈代替预测"},
             {"id": "opt_b", "label": "先做完整的市场和竞争分析再决策"},
             {"id": "opt_c", "label": "看核心假设的致命风险是否可控"},
             {"id": "opt_custom", "label": "其他/自定义答案", "requires_custom_text": True}]},
    ],
    "social": [
        {"question_type": "evidence_attitude", "prompt": "看到一项传播很广的心理学结论，你的第一反应是什么？",
         "options": [
             {"id": "opt_a", "label": "先找原始研究和样本范围"},
             {"id": "opt_b", "label": "结合自身经验判断是否可信"},
             {"id": "opt_c", "label": "结论有用就行，来源不关键"},
             {"id": "opt_custom", "label": "其他/自定义答案", "requires_custom_text": True},
             {"id": "opt_unknown", "label": "不知道或暂时无法判断", "scoring": "uncertain"}]},
    ],
    "life": [
        {"question_type": "consumption_choice", "prompt": "买大件（如家电、家具）时，你更接近哪种决策方式？",
         "options": [
             {"id": "opt_a", "label": "参数和评测横向对比，选综合最优"},
             {"id": "opt_b", "label": "明确预算和使用场景，够用就好"},
             {"id": "opt_c", "label": "看设计和体验，喜欢最重要"},
             {"id": "opt_custom", "label": "其他/自定义答案", "requires_custom_text": True}]},
    ],
    "relationship": [
        {"question_type": "boundary_setting", "prompt": "朋友多次在深夜找你倾诉同样的问题却不行动，你会怎么做？",
         "options": [
             {"id": "opt_a", "label": "继续陪聊，朋友需要时就应该在"},
             {"id": "opt_b", "label": "坦白说出自己的感受，约定更合适的交流方式"},
             {"id": "opt_c", "label": "减少回应频率，慢慢拉开距离"},
             {"id": "opt_custom", "label": "其他/自定义答案", "requires_custom_text": True}]},
    ],
    "career": [
        {"question_type": "growth_choice", "prompt": "两份工作摆在面前：一份薪资更高但方向重复，一份薪资一般但能学到新东西，你怎么选？",
         "options": [
             {"id": "opt_a", "label": "选成长空间，短期收入可以接受"},
             {"id": "opt_b", "label": "选薪资，成长可以工作外自己补"},
             {"id": "opt_c", "label": "看新方向的确定性和自己的兴趣程度"},
             {"id": "opt_custom", "label": "其他/自定义答案", "requires_custom_text": True},
             {"id": "opt_unknown", "label": "不知道或暂时无法判断", "scoring": "uncertain"}]},
    ],
    "methods": [
        {"question_type": "reasoning_style", "prompt": "面对一个复杂陌生的问题，你习惯从哪里入手？",
         "options": [
             {"id": "opt_a", "label": "先拆解结构，定义清楚问题本身"},
             {"id": "opt_b", "label": "先找相似案例，类比迁移"},
             {"id": "opt_c", "label": "先动手做最小尝试，边做边明确"},
             {"id": "opt_custom", "label": "其他/自定义答案", "requires_custom_text": True}]},
    ],
}

_GENERIC_OPINION_BANK: list[dict[str, Any]] = [
    {"question_type": "value_priority", "prompt": "在一个长期项目里，进度和质量冲突时你倾向怎么权衡？",
     "options": [
         {"id": "opt_a", "label": "质量优先，宁可推迟也要做对"},
         {"id": "opt_b", "label": "先保关键节点，质量分层处理"},
         {"id": "opt_c", "label": "进度优先，事后统一返工"},
         {"id": "opt_custom", "label": "其他/自定义答案", "requires_custom_text": True}]},
    {"question_type": "evidence_attitude", "prompt": "对与自己长期观点相反的新证据，你通常怎么处理？",
     "options": [
         {"id": "opt_a", "label": "认真评估证据强度，必要时修正观点"},
         {"id": "opt_b", "label": "先怀疑证据来源和解释方式"},
         {"id": "opt_c", "label": "观点是长期形成的，不轻易动摇"},
         {"id": "opt_custom", "label": "其他/自定义答案", "requires_custom_text": True}]},
    {"question_type": "collaboration_style", "prompt": "团队讨论陷入僵局时，你更可能做什么？",
     "options": [
         {"id": "opt_a", "label": "把分歧点写清楚，逐条对齐事实"},
         {"id": "opt_b", "label": "先找共同目标，绕开具体争议"},
         {"id": "opt_c", "label": "让数据和外部案例说话"},
         {"id": "opt_custom", "label": "其他/自定义答案", "requires_custom_text": True}]},
]

_SOCIAL_BANK: list[dict[str, Any]] = [
    {"scene": "刚认识的同事在多人聊天中把一个明显错误归因到你负责的模块。",
     "options": [
         {"id": "opt_a", "label": "马上打断，直接纠正事实"},
         {"id": "opt_b", "label": "先让对方说完，私下补充证据"},
         {"id": "opt_c", "label": "先不争论，观察是否影响实际决定"},
         {"id": "opt_custom", "label": "其他/自定义答案", "requires_custom_text": True}]},
    {"scene": "群聊里有人@你问你一个明确属于别人负责的问题。",
     "options": [
         {"id": "opt_a", "label": "直接说明并转给负责人"},
         {"id": "opt_b", "label": "简单回应后私下提醒负责人"},
         {"id": "opt_c", "label": "顺手帮着答了，不打扰别人"},
         {"id": "opt_custom", "label": "其他/自定义答案", "requires_custom_text": True}]},
    {"scene": "朋友聚会临时改到你不方便的时间，组织者直接定了新时间。",
     "options": [
         {"id": "opt_a", "label": "当场说出不方便，请大家再商量"},
         {"id": "opt_b", "label": "克服困难参加，不想扫兴"},
         {"id": "opt_c", "label": "这次缺席，之后单独约"},
         {"id": "opt_custom", "label": "其他/自定义答案", "requires_custom_text": True}]},
    {"scene": "你在会上提出方案，一位资深同事笑着说“太理想化了”。",
     "options": [
         {"id": "opt_a", "label": "请对方具体指出问题在哪"},
         {"id": "opt_b", "label": "自嘲一下，会后再找对方聊"},
         {"id": "opt_c", "label": "坚持把方案的依据讲完"},
         {"id": "opt_custom", "label": "其他/自定义答案", "requires_custom_text": True}]},
    {"scene": "有人当面真诚地夸你，但你觉得自己并没有做得那么好。",
     "options": [
         {"id": "opt_a", "label": "大方接受并道谢"},
         {"id": "opt_b", "label": "客气否认，把功劳归给运气或他人"},
         {"id": "opt_c", "label": "接受夸奖，同时补充真实存在的不足"},
         {"id": "opt_custom", "label": "其他/自定义答案", "requires_custom_text": True}]},
    {"scene": "你发现好朋友最近的某个决定可能有明显风险。",
     "options": [
         {"id": "opt_a", "label": "直接把风险讲清楚，哪怕气氛尴尬"},
         {"id": "opt_b", "label": "先问对方怎么想的，再决定说不说"},
         {"id": "opt_c", "label": "旁敲侧击提一下，不点破"},
         {"id": "opt_custom", "label": "其他/自定义答案", "requires_custom_text": True}]},
    {"scene": "线上会议里你的网络卡顿，漏听了关键信息，讨论已经继续推进。",
     "options": [
         {"id": "opt_a", "label": "立即打断请求重复那一段"},
         {"id": "opt_b", "label": "会后私下问同事补齐"},
         {"id": "opt_c", "label": "先凭上下文跟上，之后自己确认"},
         {"id": "opt_custom", "label": "其他/自定义答案", "requires_custom_text": True}]},
    {"scene": "你被拉进一个新群，群里正在讨论的话题你恰好很懂。",
     "options": [
         {"id": "opt_a", "label": "直接发言补充专业信息"},
         {"id": "opt_b", "label": "先观察群里的讨论氛围再说"},
         {"id": "opt_c", "label": "只私下回复认识的人"},
         {"id": "opt_custom", "label": "其他/自定义答案", "requires_custom_text": True}]},
    {"scene": "合作方在截止日前一天突然大幅变更需求。",
     "options": [
         {"id": "opt_a", "label": "先明确哪些能做哪些不能，书面确认"},
         {"id": "opt_b", "label": "尽力协调资源满足变更"},
         {"id": "opt_c", "label": "按原计划交付，变更另排期"},
         {"id": "opt_custom", "label": "其他/自定义答案", "requires_custom_text": True}]},
    {"scene": "你在讨论中占了上风，对方明显不快但不再回应。",
     "options": [
         {"id": "opt_a", "label": "主动缓和，确认对方观点的合理部分"},
         {"id": "opt_b", "label": "就事论事，把结论确认完结束"},
         {"id": "opt_c", "label": "给对方留台阶，换个话题"},
         {"id": "opt_custom", "label": "其他/自定义答案", "requires_custom_text": True}]},
]

# presented_at 打点登记表：question_id -> ISO 时间。进程内内存即可满足
# 13 秒限时场景；重启丢失只影响当时未提交的题目，前端可重新取题。
_PRESENTED_AT: dict[str, str] = {}
_PRESENTED_AT_MAX = 2048


def _now_iso() -> str:
    """返回 UTC ISO 时间字符串。"""
    return datetime.now(timezone.utc).isoformat()


def stamp_presented(question_id: str) -> str:
    """登记一道社交题的展示时间并返回该时间戳。"""
    if len(_PRESENTED_AT) >= _PRESENTED_AT_MAX:
        # 简单容量保护：丢弃最早一半，正常流量远达不到该规模。
        for key in list(_PRESENTED_AT)[: _PRESENTED_AT_MAX // 2]:
            _PRESENTED_AT.pop(key, None)
    value = _now_iso()
    _PRESENTED_AT[question_id] = value
    return value


def get_presented(question_id: str) -> str | None:
    """读取登记过的展示时间。"""
    return _PRESENTED_AT.get(question_id)


def build_question_llm():
    """尝试构造出题 LLM；未配置 Key 时返回 None，由调用方回退模板题库。"""
    from agent.runtime.model_builder import build_llm

    try:
        return build_llm()
    except Exception:
        return None


def _root_of(domain_id: str) -> str | None:
    """取领域 ID 的根域部分（如 computer.01.02 -> computer）。"""
    return domain_id.split(".", 1)[0] if domain_id else None


def _format_template(template: dict[str, Any], domain_id: str) -> dict[str, Any]:
    """给模板题补上题号、版本和具体领域 ID，输出契约结构。"""
    return {
        "question_id": f"opinion_{uuid4().hex[:12]}",
        "question_version": 1,
        "domain_id": domain_id,
        "question_type": template["question_type"],
        "prompt": template["prompt"],
        "options": [dict(option) for option in template["options"]],
    }


def _collect_research(domain_id: str, per_domain: int = 4) -> list[dict[str, Any]]:
    """拉取该领域的知乎公开讨论素材；失败时返回空列表，不阻断流程。"""
    node = BY_ID.get(domain_id)
    if node is None or node.level == "root":
        return []
    try:
        items = search_domain(node, per_domain)
    except Exception:
        return []
    materials = []
    for item in items:
        snippet = (item.get("snippet") or "").strip()
        if not snippet:
            continue
        materials.append({
            "title": (item.get("title") or "").strip()[:80],
            "snippet": snippet[:200],
            "content_type": item.get("content_type"),
        })
    return materials


def _extract_json_array(text: str) -> list[Any] | None:
    """从模型输出中提取第一个 JSON 数组（容忍 markdown 代码块包裹）。"""
    cleaned = re.sub(r"```(?:json)?", "", text).strip()
    start = cleaned.find("[")
    end = cleaned.rfind("]")
    if start < 0 or end <= start:
        return None
    try:
        value = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, list) else None


def _sanitize_llm_question(raw: Any, domain_id: str) -> dict[str, Any] | None:
    """校验并规范化 LLM 生成的单道观点题；不合法返回 None。"""
    if not isinstance(raw, dict):
        return None
    prompt = str(raw.get("prompt") or "").strip()
    options_raw = raw.get("options")
    if not prompt or not isinstance(options_raw, list) or not 3 <= len(options_raw) <= 6:
        return None
    options: list[dict[str, Any]] = []
    for option in options_raw:
        if not isinstance(option, dict):
            return None
        label = str(option.get("label") or "").strip()
        if not label:
            return None
        entry = {"id": str(option.get("id") or f"opt_{len(options) + 1}"), "label": label}
        if option.get("requires_custom_text"):
            entry["requires_custom_text"] = True
        if option.get("scoring"):
            entry["scoring"] = str(option["scoring"])
        options.append(entry)
    if not any(option.get("requires_custom_text") for option in options):
        options.append({"id": "opt_custom", "label": "其他/自定义答案", "requires_custom_text": True})
    return {
        "question_id": f"opinion_{uuid4().hex[:12]}",
        "question_version": 1,
        "domain_id": domain_id,
        "question_type": str(raw.get("question_type") or "open_stance"),
        "prompt": prompt,
        "options": options,
    }


def _llm_prompt_for(domain_label: str, materials: list[dict[str, Any]]) -> str:
    material_text = ""
    if materials:
        lines = [f"- 标题：{m['title']}；摘要：{m['snippet']}" for m in materials]
        material_text = "\n".join(lines)
    else:
        material_text = "（暂无素材，请基于该领域常见争议自行设计）"
    return f"""你是问卷设计师。请围绕领域「{domain_label}」设计 2 道观点选择题，用于刻画答题者的观点与判断标准。

要求：
1. 每道题 3-5 个立场平衡、互斥的选项，不设置唯一正确答案，不引导。
2. 每道题必须包含一个选项 id 为 opt_custom，表示“其他/自定义答案”，带 requires_custom_text: true。
3. 可以包含一个 id 为 opt_unknown 的选项，表示“不知道或暂时无法判断”，带 scoring: "uncertain"。
4. 优先参考下面的知乎真实讨论素材设计有争议、有取舍的问题。

输出严格的 JSON 数组，不要输出其他文字，格式：
[{{"question_type": "applied_tradeoff|value_priority|risk_tradeoff|evaluation_standard|controversy_judgment", "prompt": "题干", "options": [{{"id": "opt_a", "label": "选项文案"}}, {{"id": "opt_custom", "label": "其他/自定义答案", "requires_custom_text": true}}]}}]

知乎讨论素材：
{material_text}"""


async def _llm_opinion_questions(llm, domain_id: str) -> list[dict[str, Any]]:
    """对一个领域用 LLM 生成观点题；任何失败返回空列表。"""
    node = BY_ID.get(domain_id)
    if node is None:
        return []
    materials = await asyncio.to_thread(_collect_research, domain_id)
    try:
        response = await llm.generate(_llm_prompt_for(node.label, materials), temperature=0.4, max_tokens=1600)
    except Exception:
        return []
    raw_list = _extract_json_array(response.text)
    if not raw_list:
        return []
    questions = []
    for raw in raw_list:
        question = _sanitize_llm_question(raw, domain_id)
        if question:
            questions.append(question)
    return questions


async def generate_opinion_questions(domain_ids: list[str], count: int = 5, llm=None) -> list[dict[str, Any]]:
    """生成初始化用领域观点题。

    优先对用户所选领域做 LLM 动态出题（结合知乎公开讨论素材），
    LLM 不可用或题量不足时按根域回退内置模板题库，最后用通用题补足。
    """
    if not 1 <= count <= 10:
        raise ValueError("count must be 1..10")
    usable = [domain_id for domain_id in dict.fromkeys(domain_ids) if domain_id in BY_ID]
    questions: list[dict[str, Any]] = []
    if llm is None:
        llm = build_question_llm()
    if llm is not None:
        # 最多对前 3 个领域做 LLM 出题，控制总耗时。
        for domain_id in usable[:3]:
            if len(questions) >= count:
                break
            questions.extend(await _llm_opinion_questions(llm, domain_id))
    # 模板回退：按用户领域的根域取题，再从通用池补足。
    if len(questions) < count:
        roots = []
        for domain_id in usable:
            root = _root_of(domain_id)
            if root and root not in roots:
                roots.append(root)
        templates: list[tuple[dict[str, Any], str]] = []
        for root in roots:
            for template in _OPINION_BANK.get(root, []):
                # 优先把模板题挂到用户真实选择的叶子领域上。
                target = next((d for d in usable if _root_of(d) == root), root)
                templates.append((template, target))
        random.shuffle(templates)
        for template, target in templates:
            if len(questions) >= count:
                break
            questions.append(_format_template(template, target))
    if len(questions) < count:
        generic = list(_GENERIC_OPINION_BANK)
        random.shuffle(generic)
        for template in generic:
            if len(questions) >= count:
                break
            questions.append(_format_template(template, usable[0] if usable else "methods"))
    return questions[:count]


async def generate_social_questions(count: int = 5) -> list[dict[str, Any]]:
    """生成初始化用现实社交情景题（内置契约题库随机抽取）。"""
    if not 1 <= count <= 10:
        raise ValueError("count must be 1..10")
    picked = random.sample(_SOCIAL_BANK, min(count, len(_SOCIAL_BANK)))
    return [
        {
            "question_id": f"social_{uuid4().hex[:12]}",
            "question_version": 1,
            "question_type": "social_situation",
            "scene": template["scene"],
            "options": [dict(option) for option in template["options"]],
        }
        for template in picked
    ]
