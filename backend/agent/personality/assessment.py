"""Research-informed IPIP Big Five 50-item assessment.

IPIP items are public-domain. The Chinese text is a product translation of the
official public-domain item content; it is kept versioned so a later validated
translation can be introduced without changing historic results.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


INSTRUMENT_VERSION = "ipip-big-five-50-zh-v1"
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
    reverse: bool = False


# 10 public-domain IPIP markers per broad factor. We use translated wording,
# preserving the official keyed direction and item identity for scoring.
ITEMS: tuple[Item, ...] = (
    Item("E01", "extraversion", "我是聚会中活跃的人。"),
    Item("E02", "extraversion", "和别人待在一起时，我感到自在。"),
    Item("E03", "extraversion", "我会主动开启聊天。"),
    Item("E04", "extraversion", "在聚会中，我会和很多不同的人交谈。"),
    Item("E05", "extraversion", "我不介意成为大家关注的中心。"),
    Item("E06", "extraversion", "我不太爱说话。", True),
    Item("E07", "extraversion", "在人群中，我通常待在比较靠后的位置。", True),
    Item("E08", "extraversion", "我觉得自己没有太多可说的。", True),
    Item("E09", "extraversion", "我不喜欢吸引别人的注意。", True),
    Item("E10", "extraversion", "面对陌生人时，我通常比较安静。", True),
    Item("A01", "agreeableness", "我对他人感兴趣。"),
    Item("A02", "agreeableness", "我能体会别人的感受。"),
    Item("A03", "agreeableness", "我内心柔软，容易被他人的处境触动。"),
    Item("A04", "agreeableness", "我愿意抽时间帮助别人。"),
    Item("A05", "agreeableness", "我能感受到别人的情绪。"),
    Item("A06", "agreeableness", "我能让别人和我相处时感到自在。"),
    Item("A07", "agreeableness", "我对别人的问题不太感兴趣。", True),
    Item("A08", "agreeableness", "我会用言语伤害别人。", True),
    Item("A09", "agreeableness", "我很少关心别人的烦恼。", True),
    Item("A10", "agreeableness", "我并不怎么在意别人。", True),
    Item("C01", "conscientiousness", "我总是提前做好准备。"),
    Item("C02", "conscientiousness", "我会注意细节。"),
    Item("C03", "conscientiousness", "家务或待办事项我通常会马上处理。"),
    Item("C04", "conscientiousness", "我喜欢有秩序。"),
    Item("C05", "conscientiousness", "我会按照日程安排做事。"),
    Item("C06", "conscientiousness", "我对自己的工作要求严格。"),
    Item("C07", "conscientiousness", "我会把东西随手乱放。", True),
    Item("C08", "conscientiousness", "我常常把事情弄得一团糟。", True),
    Item("C09", "conscientiousness", "我经常忘记把东西放回原处。", True),
    Item("C10", "conscientiousness", "我会逃避自己应尽的责任。", True),
    Item("N01", "neuroticism", "我大多数时候都很放松。", True),
    Item("N02", "neuroticism", "我很少感到情绪低落。", True),
    Item("N03", "neuroticism", "我很容易感到压力。"),
    Item("N04", "neuroticism", "我会担心各种事情。"),
    Item("N05", "neuroticism", "我很容易受到干扰。"),
    Item("N06", "neuroticism", "我很容易烦恼。"),
    Item("N07", "neuroticism", "我的情绪变化比较大。"),
    Item("N08", "neuroticism", "我的情绪起伏比较频繁。"),
    Item("N09", "neuroticism", "我很容易被激怒。"),
    Item("N10", "neuroticism", "我经常感到情绪低落。"),
    Item("O01", "openness", "我的词汇量比较丰富。"),
    Item("O02", "openness", "我的想象力很丰富。"),
    Item("O03", "openness", "我经常有很好的想法。"),
    Item("O04", "openness", "我理解事物很快。"),
    Item("O05", "openness", "我会使用比较复杂的词语。"),
    Item("O06", "openness", "我会花时间思考各种事情。"),
    Item("O07", "openness", "我脑子里经常冒出很多想法。"),
    Item("O08", "openness", "我很难理解抽象的想法。", True),
    Item("O09", "openness", "我对抽象的想法不感兴趣。", True),
    Item("O10", "openness", "我的想象力不太好。", True),
)
ITEM_BY_ID = {item.id: item for item in ITEMS}


def public_questions() -> dict[str, Any]:
    """Return the client-safe questionnaire; keyed direction stays private."""

    return {
        "instrument_version": INSTRUMENT_VERSION,
        "model": "big_five",
        "source": "IPIP public-domain Big-Five Factor Markers",
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

    values: dict[str, list[int]] = {dimension: [] for dimension in DIMENSIONS}
    for item in ITEMS:
        if item.id in answers:
            value = 6 - answers[item.id] if item.reverse else answers[item.id]
            values[item.dimension].append(value)

    scores: dict[str, float | None] = {}
    means: dict[str, float | None] = {}
    completeness: dict[str, float] = {}
    for dimension, dimension_values in values.items():
        completeness[dimension] = round(len(dimension_values) / 10, 2)
        if not dimension_values:
            means[dimension] = None
            scores[dimension] = None
            continue
        mean = sum(dimension_values) / len(dimension_values)
        means[dimension] = round(mean, 3)
        scores[dimension] = round((mean - 1) * 2.5, 2)

    count = len(answers)
    frequency = {value: list(answers.values()).count(value) for value in range(1, 6)}
    straightline = count >= 20 and max(frequency.values()) == count
    status = "completed" if count == len(ITEMS) and not straightline else "quality_review" if count == len(ITEMS) else "partial"
    flags: list[str] = []
    if count < len(ITEMS):
        flags.append("missing_answers")
    if straightline:
        flags.append("straightline_response")
    if any(len(dimension_values) < 8 for dimension_values in values.values()):
        flags.append("dimension_incomplete")
    data_quality = round(max(0.0, min(1.0, (count / len(ITEMS)) * (0.7 if straightline else 1.0))), 2)
    return {
        "model": "big_five",
        "instrument_version": INSTRUMENT_VERSION,
        "assessment_id": assessment_id,
        "scores": scores,
        "raw_means": means,
        "data_quality": data_quality,
        "confidence": data_quality,
        "status": status,
        "source": "self_report",
        "style_tags": _style_tags(scores),
        "validity": {"answered_count": count, "total_count": len(ITEMS), "flags": flags, "usable": count >= 40 and not straightline},
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
