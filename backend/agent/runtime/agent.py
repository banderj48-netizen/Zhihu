"""数字分身 Agent 运行时编排。

Agent 只负责把当前问题、固定画像和业务代码已经准备好的检索上下文交给 LLM。
本模块不会注册工具，也不会自行访问数据库、Chroma 或主动触发检索。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Mapping
from uuid import uuid4

from agent.runtime.llm import LLM, LLMResponse


ContextBuilder = Callable[..., Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class AgentReply:
    """Agent 对外返回的回答及其来源元数据。"""

    answer: str
    confidence: float
    used_memory_ids: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    model: str = ""
    request_id: str = ""
    raw_context: Mapping[str, Any] = field(default_factory=dict)


class Agent:
    """数字分身 Agent。

    Agent 的职责是编排，而不是检索：调用方把 ``context_builder`` 和 ``LLM``
    注入后，Agent 在一次 ``answer`` 调用中显式请求上下文、构建分区 Prompt、
    调用模型并提取引用元数据。检索函数不会暴露给模型，因此模型不能自主检索。
    """

    def __init__(self, llm: LLM, context_builder: ContextBuilder) -> None:
        """创建 Agent，并注入模型客户端和上下文组装函数。"""
        self._llm = llm
        self._context_builder = context_builder

    async def answer(
        self,
        user_id: str,
        question: str,
        *,
        conversation_id: str | None = None,
        max_tokens: int = 1200,
        request_id: str | None = None,
    ) -> AgentReply:
        """显式组装上下文并生成一次回答。"""
        if not question.strip():
            raise ValueError("question 不能为空")
        actual_request_id = request_id or str(uuid4())
        context = await self._context_builder(user_id, question, conversation_id=conversation_id)
        prompt = self.build_prompt(context, question)
        response = await self._llm.generate(prompt, max_tokens=max_tokens, request_id=actual_request_id)
        return self._make_reply(response, context, actual_request_id)

    @staticmethod
    def build_prompt(context: Mapping[str, Any], question: str) -> str:
        """将上下文按固定画像、动态记忆、原始证据和聊天历史分区序列化。

        使用 JSON 分区而不是把所有字段拼成无边界字符串，模型可以清楚区分事实、
        推断、来源和行为规则；Prompt 中同时明确禁止编造经历和观点。
        """
        profile = context.get("profile") or {}
        return "\n".join(
            [
                "# 任务",
                "根据用户画像和已检索证据回答问题。不得编造用户经历、能力或观点；证据不足时明确说明不确定。",
                "# 固定画像（直接来自数据库）",
                json.dumps(profile, ensure_ascii=False, default=str),
                "# 动态画像记忆（经过权限过滤）",
                json.dumps(context.get("retrieved_memories", {}), ensure_ascii=False, default=str),
                "# 原始资料证据",
                json.dumps(context.get("source_documents", []), ensure_ascii=False, default=str),
                "# 历史聊天上下文",
                json.dumps(context.get("chat_history", []), ensure_ascii=False, default=str),
                "# 检索提示",
                str(context.get("notice", "")),
                "# 用户问题",
                question,
            ]
        )
    @staticmethod
    def _make_reply(response: LLMResponse, context: Mapping[str, Any], request_id: str) -> AgentReply:
        """从结构化检索结果提取记忆和证据 ID，形成稳定的回答契约。"""
        memory_ids: list[str] = []
        for values in (context.get("retrieved_memories") or {}).values():
            if isinstance(values, list):
                memory_ids.extend(str(item["memory_id"]) for item in values if isinstance(item, Mapping) and item.get("memory_id"))
        evidence_ids = [str(item["document_id"]) for item in context.get("source_documents", []) if isinstance(item, Mapping) and item.get("document_id")]
        has_sources = bool(memory_ids or evidence_ids or context.get("chat_history"))
        confidence = 0.7 if has_sources else 0.35
        return AgentReply(
            answer=response.text,
            confidence=confidence,
            used_memory_ids=tuple(dict.fromkeys(memory_ids)),
            evidence_refs=tuple(dict.fromkeys(evidence_ids)),
            model=response.model,
            request_id=request_id,
            raw_context={"generated_at": datetime.now(timezone.utc).isoformat(), "retrieval_meta": context.get("retrieval_meta", {})},
        )
