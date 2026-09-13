"""双 Agent 对话契合度评判。"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

from agent.runtime.llm import LLM


@dataclass(frozen=True)
class DialogueEvaluation:
    """评判模型输出的标准结果。"""

    score: float
    summary: str
    dimensions: Mapping[str, Any]
    raw_result: Mapping[str, Any]


class DialogueEvaluator:
    """使用独立 LLM 对完整双 Agent 对话进行结构化评分。"""

    def __init__(self, llm: LLM) -> None:
        """注入评判模型。"""
        self._llm = llm

    async def evaluate(self, transcript: list[Mapping[str, Any]], *, identity_a: str = "", identity_b: str = "") -> DialogueEvaluation:
        """请求评判模型并校验 0 到 1 范围内的 JSON 评分。"""
        prompt = json.dumps({"task": "评估两名数字分身的契合程度，只返回JSON", "identity_a": identity_a, "identity_b": identity_b, "transcript": transcript, "schema": {"score": "0..1", "summary": "string", "dimensions": "object"}}, ensure_ascii=False, default=str)
        response = await self._llm.generate(prompt, temperature=0, max_tokens=500)
        try:
            data = json.loads(response.text)
            score = float(data["score"])
            if not 0 <= score <= 1:
                raise ValueError
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise ValueError("评判模型必须返回包含 0..1 score 的 JSON") from exc
        return DialogueEvaluation(score, str(data.get("summary", "")), data.get("dimensions") or {}, data)

