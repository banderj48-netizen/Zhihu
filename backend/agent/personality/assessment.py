"""Research-informed 25-item Big Five assessment (BFI-2-S methodology).

参照 Soto & John (2017) 的 BFI-2 / BFI-2-S 短版方法论：五个大五维度，每维度
5 题、覆盖该维度的三个侧面（facet），正反向计分平衡；题干采用工作、社交、
情绪与决策场景的综合描述，适合轻量初始化问卷。量表版本化保存，便于后续
替换为经过效度检验的正式中文版而不影响历史结果。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


INSTRUMENT_VERSION = "bfi2-s-style-25-zh-v1"
DIMENSIONS = ("extraversion", "agreeableness", "conscientiousness", "neuroticism", "openness")
DIMENSION_LABELS = {
    "extraversion": "外向性",
    "agreeableness": "宜人性",
    "conscientiousness": "尽责性",
    "neuroticism": "情绪敏感性",
    "openness": "开放性",
}
SCALE_LABELS = ["非常不符合", "较不符合", "一般", "较符合", "非常符合"]


@dataclass(frozen=True)
class Item:
    id: str
    dimension: str
    text: str
    facet: str = ""
    reverse: bool = False


# 每维度 5 题：覆盖 BFI-2 的三个侧面，反向题保持平衡，题目为综合情景描述。
ITEMS: tuple[Item, ...] = (
    # 外向性：社交性 / 果断性 / 活力水平
    Item("E01", "extraversion", "在陌生的场合，我很快就能和周围的人聊起来，还常常成为带动气氛的那一个。", "sociability+energy"),
    Item("E02", "extraversion", "小组讨论时我习惯第一个发言，也愿意牵头组织大家一起做事。", "assertiveness"),
    Item("E03", "extraversion", "热闹的聚会结束后我需要很久才能缓过来，平时也更喜欢一个人安静地做事。", "sociability", True),
    Item("E04", "extraversion", "需要当众表达观点或为自己争取机会时，我倾向于等别人先开口。", "assertiveness", True),
    Item("E05", "extraversion", "和陌生人同桌吃饭，我也能自然地找到话题，并享受这个过程。", "sociability"),
    # 宜人性：同情心 / 尊重他人 / 信任
    Item("A01", "agreeableness", "看到别人遇到难处，我会主动询问并尽力搭把手，即使我们并不熟。", "compassion"),
    Item("A02", "agreeableness", "意见不合时，我也会先完整听完对方的理由，再平和地说出自己的看法。", "respectfulness"),
    Item("A03", "agreeableness", "讨论问题时我更关注把事情说清楚，常常顾不上照顾对方的情绪。", "compassion", True),
    Item("A04", "agreeableness", "我默认大多数人是善意的，愿意把重要的事托付给别人。", "trust"),
    Item("A05", "agreeableness", "别人的情绪起伏不太会影响我，我很少为别人的处境分心。", "compassion", True),
    # 尽责性：条理性 / 勤奋高效 / 责任感
    Item("C01", "conscientiousness", "我的日程、文件和待办都有清晰的安排，并且会按计划推进到完成。", "organization+diligence"),
    Item("C02", "conscientiousness", "做重要决定前，我会系统地收集信息、评估风险，而不是边走边看。", "productiveness"),
    Item("C03", "conscientiousness", "我经常拖到截止日期前才突击，东西也常常随手放了就忘。", "organization", True),
    Item("C04", "conscientiousness", "答应别人的事，哪怕自己吃亏，我也会按时做到。", "responsibility"),
    Item("C05", "conscientiousness", "我喜欢随机应变，太详细的计划对我来说反而是一种束缚。", "productiveness", True),
    # 情绪敏感性（负面情绪性）：焦虑 / 情绪波动 / 恢复力
    Item("N01", "neuroticism", "任务还没有完成时，我会反复担心结果，晚上也容易因此睡不踏实。", "anxiety"),
    Item("N02", "neuroticism", "遇到突发状况或被批评时，我能较快平静下来并着手处理。", "emotional_volatility", True),
    Item("N03", "neuroticism", "我的情绪容易被小事带动，一天之内可能起落好几次。", "emotional_volatility"),
    Item("N04", "neuroticism", "我时常莫名感到低落，或对平时喜欢的事提不起劲。", "depression"),
    Item("N05", "neuroticism", "即使压力很大的阶段，我依然能保持胃口、睡眠和基本的好心情。", "anxiety", True),
    # 开放性：智识好奇 / 审美敏感 / 创造想象
    Item("O01", "openness", "接触新概念、新工具或跨领域话题时，我会主动花时间深入钻研。", "intellectual_curiosity"),
    Item("O02", "openness", "我常被艺术、设计或自然中的美打动，也会专门安排时间去体验。", "aesthetic_sensitivity"),
    Item("O03", "openness", "我常有一些跳出常规的想法，喜欢把不同领域的东西联系起来尝试。", "creative_imagination"),
    Item("O04", "openness", "我偏好成熟稳妥的做法，对新奇但还没被验证过的方案兴趣不大。", "intellectual_curiosity", True),
    Item("O05", "openness", "抽象的理论讨论让我觉得离实际太远，我更愿意谈具体怎么做。", "creative_imagination", True),
)
ITEM_BY_ID = {item.id: item for item in ITEMS}
ITEMS_PER_DIMENSION = {dimension: sum(1 for item in ITEMS if item.dimension == dimension) for dimension in DIMENSIONS}


def public_questions() -> dict[str, Any]:
    """Return the client-safe questionnaire; keyed direction stays private."""

    return {
        "instrument_version": INSTRUMENT_VERSION,
        "model": "big_five",
        "source": "BFI-2-S methodology (Soto & John, 2017) adapted 25-item zh version",
        "scale": {"min": 1, "max": 5, "labels": SCALE_LABELS},
        "dimensions": [{"id": key, "label": DIMENSION_LABELS[key]} for key in DIMENSIONS],
        "items": [{"id": item.id, "text": item.text} for item in ITEMS],
    }


def _style_tags(scores: dict[str, float | None]) -> list[str]:
    tags: list[str] = []
    if (value := scores.get("extraversion")) is not None:
        tags.append("社交克制" if value < 4.5 else "主动社交" if value >= 6.5 else "社交适中")
    if (value := scores.get("agreeableness")) is not None:
        tags.append("表达直接" if value < 4.5 else "照顾感受" if value >= 6.5 else "注意分寸")
    if (value := scores.get("conscientiousness")) is not None and value >= 6.5:
        tags.append("有计划")
    if (value := scores.get("openness")) is not None and value >= 6.5:
        tags.append("乐于探索")
    if (value := scores.get("neuroticism")) is not None:
        tags.append("情绪稳定" if value < 4.5 else "感受敏锐" if value >= 6.5 else "情绪反应适中")
    return tags


def score_assessment(answers: dict[str, int], assessment_id: str, notes: str | None = None) -> dict[str, Any]:
    unknown = sorted(set(answers) - set(ITEM_BY_ID))
    invalid = sorted(key for key, value in answers.items() if isinstance(value, bool) or not isinstance(value, int) or value not in range(1, 6))
    if unknown or invalid:
        raise ValueError(f"invalid_answers: unknown={unknown}, invalid={invalid}")

    total = len(ITEMS)
    values: dict[str, list[int]] = {dimension: [] for dimension in DIMENSIONS}
    for item in ITEMS:
        if item.id in answers:
            value = 6 - answers[item.id] if item.reverse else answers[item.id]
            values[item.dimension].append(value)

    scores: dict[str, float | None] = {}
    means: dict[str, float | None] = {}
    completeness: dict[str, float] = {}
    for dimension, dimension_values in values.items():
        completeness[dimension] = round(len(dimension_values) / ITEMS_PER_DIMENSION[dimension], 2)
        if not dimension_values:
            means[dimension] = None
            scores[dimension] = None
            continue
        mean = sum(dimension_values) / len(dimension_values)
        means[dimension] = round(mean, 3)
        scores[dimension] = round((mean - 1) * 2.5, 2)

    count = len(answers)
    frequency = {value: list(answers.values()).count(value) for value in range(1, 6)}
    # 直线作答检查：过半题目选择同一档且无变化视为无效作答倾向。
    straightline = count >= max(10, total // 2) and max(frequency.values()) == count
    status = "completed" if count == total and not straightline else "quality_review" if count == total else "partial"
    flags: list[str] = []
    if count < total:
        flags.append("missing_answers")
    if straightline:
        flags.append("straightline_response")
    # 单维度作答率低于 80% 视为维度不完整。
    if any(len(dimension_values) < int(ITEMS_PER_DIMENSION[dimension] * 0.8) for dimension, dimension_values in values.items()):
        flags.append("dimension_incomplete")
    data_quality = round(max(0.0, min(1.0, (count / total) * (0.7 if straightline else 1.0))), 2)
    usable_threshold = int(total * 0.8)
    return {
        "model": "big_five",
        "instrument_version": INSTRUMENT_VERSION,
        "assessment_id": assessment_id,
        "scores": scores,
        "raw_means": means,
        "completeness": completeness,
        "data_quality": data_quality,
        "confidence": data_quality,
        "status": status,
        "source": "self_report",
        "style_tags": _style_tags(scores),
        "validity": {"answered_count": count, "total_count": total, "flags": flags, "usable": count >= usable_threshold and not straightline},
        "notes": notes,
        "raw_answers": answers,
        "privacy": "private",
        "share": False,
    }


def render_personality(personality: dict[str, Any] | str | None) -> str:
    if not personality:
        return "尚未完成性格测评，具体反应以条件记忆和当前证据为准。"
    if isinstance(personality, str):
        return personality
    scores = personality.get("scores") or {}
    parts = [f"{DIMENSION_LABELS[key]} {scores[key]}/10" for key in DIMENSIONS if scores.get(key) is not None]
    tags = personality.get("style_tags") or []
    state = "已完成" if personality.get("validity", {}).get("usable") else "数据不足或质量较低"
    text = f"Big Five（{state}）：" + "、".join(parts)
    return text + (f"。表达倾向参考：{'、'.join(tags)}。" if tags else "。")


def export_personality(personality: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return the non-answer portion safe for a private card extension."""

    if not personality:
        return None
    allowed = ("model", "instrument_version", "assessment_id", "scores", "confidence", "data_quality", "status", "source", "style_tags")
    return {key: personality[key] for key in allowed if key in personality}
