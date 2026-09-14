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
# 观点题为多约束综合权衡题：题干同时给出场景、目标和冲突条件，
# 选项代表不同的价值排序与决策风格，彼此互斥且无明显倾向。
# ---------------------------------------------------------------------------

_OPINION_BANK: dict[str, list[dict[str, Any]]] = {
    "computer": [
        {"question_type": "applied_tradeoff", "prompt": "核心系统要在两周内上线，测试覆盖只完成了七成：性能压测通过，但两个边缘模块没有回归。业务方催得紧，你负责技术决策。",
         "options": [
             {"id": "opt_a", "label": "按期上线，边缘问题用灰度和监控兜底，出问题热修"},
             {"id": "opt_b", "label": "延迟一周补齐回归，用数据说服业务方接受延期"},
             {"id": "opt_c", "label": "拆分上线：核心路径先发，边缘模块稳定后再放开"},
             {"id": "opt_custom", "label": "其他/自定义答案", "requires_custom_text": True},
             {"id": "opt_unknown", "label": "不知道或暂时无法判断", "scoring": "uncertain"}]},
        {"question_type": "value_priority", "prompt": "你主导的技术方案评审中，一位初级同事当面指出你的设计有个隐患，而且他说得基本正确，但修正会推翻已完成的两周工作。",
         "options": [
             {"id": "opt_a", "label": "公开承认并重构，把这次复盘做成团队案例"},
             {"id": "opt_b", "label": "本期加防御性补丁，下个周期再彻底改"},
             {"id": "opt_c", "label": "先评估隐患触发概率，再决定改不改"},
             {"id": "opt_custom", "label": "其他/自定义答案", "requires_custom_text": True}]},
    ],
    "entertainment": [
        {"question_type": "evaluation_standard", "prompt": "一部话题作品上线：口碑两极、评分机构分数不高，但题材突破很大，而你信任的朋友都说“值得看”。你的观看决策更接近哪种？",
         "options": [
             {"id": "opt_a", "label": "自己完整体验后再评价，不被任何一方带节奏"},
             {"id": "opt_b", "label": "先看差评理由，能接受再入坑"},
             {"id": "opt_c", "label": "题材突破本身就值票价，缺点可以容忍"},
             {"id": "opt_custom", "label": "其他/自定义答案", "requires_custom_text": True},
             {"id": "opt_unknown", "label": "不知道或暂时无法判断", "scoring": "uncertain"}]},
        {"question_type": "controversy_judgment", "prompt": "一款你玩了多年的游戏被爆出剧情抄袭争议：实锤证据部分成立，制作组道过歉，下一部作品预告又很有诚意。",
         "options": [
             {"id": "opt_a", "label": "分开看：继续玩，但持续公开监督它的抄袭问题"},
             {"id": "opt_b", "label": "用钱包投票，弃坑直到它拿出原创证明"},
             {"id": "opt_c", "label": "版权方没追究，玩家不必替人维权，好玩就行"},
             {"id": "opt_custom", "label": "其他/自定义答案", "requires_custom_text": True}]},
    ],
    "medicine": [
        {"question_type": "risk_tradeoff", "prompt": "体检报告显示一项肿瘤标志物轻度异常（略高于参考值），无任何症状，医生说“大概率是炎症，也可以做个增强检查排除”，增强检查有创且自费。",
         "options": [
             {"id": "opt_a", "label": "先按炎症处理，一个月后复查指标趋势"},
             {"id": "opt_b", "label": "立即做增强检查，花钱买确定"},
             {"id": "opt_c", "label": "换两家医院听听不同意见再决定"},
             {"id": "opt_custom", "label": "其他/自定义答案", "requires_custom_text": True},
             {"id": "opt_unknown", "label": "不知道或暂时无法判断", "scoring": "uncertain"}]},
    ],
    "business": [
        {"question_type": "decision_basis", "prompt": "你在考虑是否加入一个早期团队：创始人靠谱、方向你认同，但商业模式还没验证，薪酬只有现在的一半，期权占比不小。",
         "options": [
             {"id": "opt_a", "label": "先兼职参与三个月，用真实投入验证再全职"},
             {"id": "opt_b", "label": "赌赛道和人的权重最高，降薪直接加入"},
             {"id": "opt_c", "label": "先做完整的行业与竞品调研，再谈条件"},
             {"id": "opt_custom", "label": "其他/自定义答案", "requires_custom_text": True}]},
    ],
    "social": [
        {"question_type": "evidence_attitude", "prompt": "一篇讲“某习惯影响寿命”的研究解读刷了屏：样本量大、媒体标题吓人，但你发现它是相关性研究而非因果实验，评论区已经吵翻。",
         "options": [
             {"id": "opt_a", "label": "回到论文原文，看研究设计和混杂变量再下结论"},
             {"id": "opt_b", "label": "相关性也值得参考，宁可信其有地调整习惯"},
             {"id": "opt_c", "label": "等几个月看领域内有没有反驳或重复研究"},
             {"id": "opt_custom", "label": "其他/自定义答案", "requires_custom_text": True}]},
    ],
    "life": [
        {"question_type": "consumption_choice", "prompt": "搬家要买一台大件家电：预算内 A 款参数全面领先但品牌小众售后一般，B 款是你用了十年的老品牌、参数中游但售后口碑极好。",
         "options": [
             {"id": "opt_a", "label": "选 A：核心性能是长期体验，售后是小概率事件"},
             {"id": "opt_b", "label": "选 B：可靠性优先，参数差距日常感知有限"},
             {"id": "opt_c", "label": "看拆解和长期用户评价，参数和品牌都不迷信"},
             {"id": "opt_custom", "label": "其他/自定义答案", "requires_custom_text": True}]},
    ],
    "relationship": [
        {"question_type": "boundary_setting", "prompt": "多年好友陷入反复的困境，每次都深夜找你倾诉两三个小时，你给出的建议他从没执行过，你最近项目压力也很大。",
         "options": [
             {"id": "opt_a", "label": "坦白说出自己的状态，约定更合适的倾诉方式和频率"},
             {"id": "opt_b", "label": "继续陪：朋友需要的可能不是建议，是有人在场"},
             {"id": "opt_c", "label": "建议他寻求专业咨询，自己退到支持位"},
             {"id": "opt_custom", "label": "其他/自定义答案", "requires_custom_text": True}]},
    ],
    "career": [
        {"question_type": "growth_choice", "prompt": "你拿到两个机会：大厂核心团队的高级岗位，做你已经很熟的方向；小公司负责人岗位，要带团队、碰新领域，薪资略低但期权可观。",
         "options": [
             {"id": "opt_a", "label": "去大厂：把长板磨到顶尖，平台和背书也值钱"},
             {"id": "opt_b", "label": "去小公司：综合能力的窗口期比薪资重要"},
             {"id": "opt_c", "label": "看小公司的现金流和老板兑现历史的证据"},
             {"id": "opt_custom", "label": "其他/自定义答案", "requires_custom_text": True},
             {"id": "opt_unknown", "label": "不知道或暂时无法判断", "scoring": "uncertain"}]},
    ],
    "methods": [
        {"question_type": "reasoning_style", "prompt": "你接手一个完全陌生的复杂问题（新领域、多方利益、信息残缺），只有两周时间给出可信结论。",
         "options": [
             {"id": "opt_a", "label": "先定义问题和拆解结构，再逐块找证据填空"},
             {"id": "opt_b", "label": "先找三个类似案例的解法，类比迁移后本地化"},
             {"id": "opt_c", "label": "先做最小成本尝试，用反馈修正方向"},
             {"id": "opt_custom", "label": "其他/自定义答案", "requires_custom_text": True}]},
    ],
    "law_policy": [
        {"question_type": "policy_tradeoff", "prompt": "某平台新规讨论：为保护用户隐私，要求默认匿名化所有公开数据，但这会显著提高研究者做公共分析的门槛。",
         "options": [
             {"id": "opt_a", "label": "隐私优先：可以设计申请制的研究通道作为补偿"},
             {"id": "opt_b", "label": "公共价值优先：匿名化让研究成本过高，应该分级公开"},
             {"id": "opt_c", "label": "技术方案优先：差分隐私等手段可以两者兼顾"},
             {"id": "opt_custom", "label": "其他/自定义答案", "requires_custom_text": True}]},
    ],
    "sports": [
        {"question_type": "training_choice", "prompt": "你备战一场三个月后的比赛，同时工作进入旺季。教练的计划强度很高，你评估自己平均每周只能保证六成训练量。",
         "options": [
             {"id": "opt_a", "label": "砍掉次要训练，集中保证关键课的完成质量"},
             {"id": "opt_b", "label": "降低整体强度按完整计划走，完赛优先"},
             {"id": "opt_c", "label": "顺其自然，能练多少练多少，享受过程"},
             {"id": "opt_custom", "label": "其他/自定义答案", "requires_custom_text": True}]},
    ],
    "humanities": [
        {"question_type": "interpretation_stance", "prompt": "读一本经典著作时，你的解读方式更接近哪种？",
         "options": [
             {"id": "opt_a", "label": "先放回历史语境理解作者，再谈当下的意义"},
             {"id": "opt_b", "label": "经典的意义在于当下，用它映照现实问题"},
             {"id": "opt_c", "label": "对照多家注解和批评，形成自己的综合判断"},
             {"id": "opt_custom", "label": "其他/自定义答案", "requires_custom_text": True}]},
    ],
}

_GENERIC_OPINION_BANK: list[dict[str, Any]] = [
    {"question_type": "value_priority", "prompt": "一个你负责的长期项目进行到中段，外部环境突变让原目标的价值打了对折，沉没成本已经很高，团队士气正盛。",
     "options": [
         {"id": "opt_a", "label": "及时止损调整方向，诚实同步团队重新对焦"},
         {"id": "opt_b", "label": "坚持完成原目标，半途而废的代价更大"},
         {"id": "opt_c", "label": "保留原目标但降低投入，把资源挪去试探新方向"},
         {"id": "opt_custom", "label": "其他/自定义答案", "requires_custom_text": True}]},
    {"question_type": "evidence_attitude", "prompt": "一个你坚持多年的观点，最近连续遇到三个来自你尊重的人的反驳和新证据。",
     "options": [
         {"id": "opt_a", "label": "公开重新审视，观点该让位于证据"},
         {"id": "opt_b", "label": "先严格检查反驳本身是否成立，再决定"},
         {"id": "opt_c", "label": "核心立场不变，吸收有效部分修正细节"},
         {"id": "opt_custom", "label": "其他/自定义答案", "requires_custom_text": True}]},
    {"question_type": "collaboration_style", "prompt": "跨团队项目推进会上，两方对方案的分歧已经从技术层面上升到立场层面，会议即将不欢而散，你是中间方。",
     "options": [
         {"id": "opt_a", "label": "当场把分歧还原成可验证的事实问题，逐条对齐"},
         {"id": "opt_b", "label": "先搁置争议部分，推动双方先在共识上合作"},
         {"id": "opt_c", "label": "引入外部专家或数据，让第三方打破僵局"},
         {"id": "opt_custom", "label": "其他/自定义答案", "requires_custom_text": True}]},
]

# 社交情景题：每题叠加多重现实动态（关系亲疏 + 场合公开程度 + 时间压力 +
# 利益或情感风险），选项描述“行动 + 方式”的组合，用于刻画下意识反应模式。
_SOCIAL_BANK: list[dict[str, Any]] = [
    {"scene": "部门会议上，领导刚讲完方案，你发现其中一处数据错误会让结论反转；散会前十分钟，提出来需要当场重新讨论。",
     "options": [
         {"id": "opt_a", "label": "会上直接指出错误并说明依据，请求当场澄清"},
         {"id": "opt_b", "label": "会后单独找领导，附上完整的数据核查"},
         {"id": "opt_c", "label": "先在群里补充正确数据，不点明谁错"},
         {"id": "opt_custom", "label": "其他/自定义答案", "requires_custom_text": True}]},
    {"scene": "好朋友创业拉你入伙：项目你不看好，但他经济上已经押上了全部身家，正等你答复，气氛很热切。",
     "options": [
         {"id": "opt_a", "label": "当面把不看好的理由一条条讲清楚"},
         {"id": "opt_b", "label": "婉拒参与但说明会以别的方式支持"},
         {"id": "opt_c", "label": "先不表态，约定一周内给正式答复"},
         {"id": "opt_custom", "label": "其他/自定义答案", "requires_custom_text": True}]},
    {"scene": "你组织的朋友聚会上，两个朋友因为旧矛盾当场吵起来，其他人都看向作为组织者的你。",
     "options": [
         {"id": "opt_a", "label": "立即打断转移话题，会后分别再聊"},
         {"id": "opt_b", "label": "当场居中调解，把话说开"},
         {"id": "opt_c", "label": "让他们吵完，相信成年人能自己收场"},
         {"id": "opt_custom", "label": "其他/自定义答案", "requires_custom_text": True}]},
    {"scene": "合作方在截止日前一天推翻了已确认两周的需求，还暗示“不配合就找你们领导”；你的团队这周已经连续加班。",
     "options": [
         {"id": "opt_a", "label": "先书面确认变更范围和代价，再谈配合"},
         {"id": "opt_b", "label": "顶住压力按原范围交付，变更走正式流程"},
         {"id": "opt_c", "label": "尽力协调团队满足变更，维护关系优先"},
         {"id": "opt_custom", "label": "其他/自定义答案", "requires_custom_text": True}]},
    {"scene": "你在会上提的方案被一位资深同事当众说“太理想化”，领导没有表态，会议室安静下来。",
     "options": [
         {"id": "opt_a", "label": "当场请对方具体指出问题，就事论事讨论"},
         {"id": "opt_b", "label": "笑着接住，会后私下找对方细聊"},
         {"id": "opt_c", "label": "把方案的依据和数据讲完，用内容回应"},
         {"id": "opt_custom", "label": "其他/自定义答案", "requires_custom_text": True}]},
    {"scene": "你无意间听到同事在茶水间议论你的失误，对方还不知道你在门外，说的是你上周确实搞砸的那件事。",
     "options": [
         {"id": "opt_a", "label": "推门进去，坦然承认失误并同步补救进展"},
         {"id": "opt_b", "label": "默默走开，自己先把问题补上"},
         {"id": "opt_c", "label": "事后找议论的同事聊，了解真实评价"},
         {"id": "opt_custom", "label": "其他/自定义答案", "requires_custom_text": True}]},
    {"scene": "家人在家庭群里转发了一条明显是谣言的健康文章，还专门@你让你照做，长辈们都在附和。",
     "options": [
         {"id": "opt_a", "label": "在群里贴出权威辟谣来源，温和说明"},
         {"id": "opt_b", "label": "私聊长辈一对一解释，不在群里纠正"},
         {"id": "opt_c", "label": "不反驳，自己注意辨别就行"},
         {"id": "opt_custom", "label": "其他/自定义答案", "requires_custom_text": True}]},
    {"scene": "线上会议网络卡顿，你漏听了关键结论，讨论已经推进到表决环节，马上要轮到你表态。",
     "options": [
         {"id": "opt_a", "label": "立即打断请求重复那一段结论"},
         {"id": "opt_b", "label": "凭已有上下文先表态，会后私下确认"},
         {"id": "opt_c", "label": "发言时先声明可能漏听，请大家补充"},
         {"id": "opt_custom", "label": "其他/自定义答案", "requires_custom_text": True}]},
    {"scene": "你被拉进一个新工作群，里面正在讨论的问题恰好是你的专业领域，且讨论方向有明显偏差，但群里还没有你认识的人。",
     "options": [
         {"id": "opt_a", "label": "直接发言指出偏差并给出依据"},
         {"id": "opt_b", "label": "先观察一轮讨论氛围，找合适切入点再说"},
         {"id": "opt_c", "label": "私下加讨论最激烈的人，单独交流"},
         {"id": "opt_custom", "label": "其他/自定义答案", "requires_custom_text": True}]},
    {"scene": "你辛苦两周的成果被临时叫停，原因是领导层战略调整；宣布时领导当着大家问你“能理解吧”。",
     "options": [
         {"id": "opt_a", "label": "当场说出自己的遗憾，同时确认新方向"},
         {"id": "opt_b", "label": "先表态配合，私下再找领导聊感受"},
         {"id": "opt_c", "label": "接受现实，关注成果能否在新方向复用"},
         {"id": "opt_custom", "label": "其他/自定义答案", "requires_custom_text": True}]},
    {"scene": "争论中你占了上风，对方明显不快但不再回应；你意识到自己刚才的措辞重了，而周围人都在看。",
     "options": [
         {"id": "opt_a", "label": "当场缓和，明确认可对方观点的合理部分"},
         {"id": "opt_b", "label": "就事论事把结论确认完，会后私下修复关系"},
         {"id": "opt_c", "label": "给对方留台阶，主动换个轻松话题"},
         {"id": "opt_custom", "label": "其他/自定义答案", "requires_custom_text": True}]},
    {"scene": "你发现平时关照你的同事在报销单上做了手脚，金额不大，但制度上属于红线；你们下周还要一起赶一个重要项目。",
     "options": [
         {"id": "opt_a", "label": "先私下提醒他改掉，不上报"},
         {"id": "opt_b", "label": "按制度向上反映，回避私人交情"},
         {"id": "opt_c", "label": "不介入，但不再为其报销签字"},
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
