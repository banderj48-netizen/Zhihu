"""双 Agent 对话开始前的话题筛选 LangGraph。"""
from __future__ import annotations

import json
import os
import random
from typing import Any, Awaitable, Callable, Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from agent.runtime.llm import LLM


class TopicGateState(TypedDict, total=False):
    """话题门控图的运行状态。"""

    avatar_a_id: str
    avatar_b_id: str
    user_id_a: str
    user_id_b: str
    scene_id: str
    topic_mode: str
    opinions_a: list[dict[str, Any]]
    opinions_b: list[dict[str, Any]]
    shared_topics: list[dict[str, Any]]
    current_topic: str
    topic_source: str
    interest_score: float
    interest_decision: Literal["interested", "rejected"]
    interest_reason: str
    refusal_response: str


class TopicGateGraph:
    """使用 LangGraph 编排观点交集与接收方兴趣判断。"""

    def __init__(self, llm: LLM, context_builder: Any) -> None:
        """注入回答模型和显式上下文构建函数。"""
        self._llm = llm
        self._context_builder = context_builder
        builder = StateGraph(TopicGateState)
        builder.add_node("load_opinions", self.load_opinions)
        builder.add_node("find_shared_topics", self.find_shared_topics)
        builder.add_node("select_shared_topic", self.select_shared_topic)
        builder.add_node("select_random_topic", self.select_random_topic)
        builder.add_node("ask_interest", self.ask_interest)
        builder.add_node("persist_refusal", self.persist_refusal)
        builder.add_edge(START, "load_opinions")
        builder.add_edge("load_opinions", "find_shared_topics")
        builder.add_conditional_edges("find_shared_topics", self._route_topic, {"shared": "select_shared_topic", "random": "select_random_topic"})
        builder.add_edge("select_shared_topic", "ask_interest")
        builder.add_edge("select_random_topic", "ask_interest")
        builder.add_conditional_edges("ask_interest", self._route_interest, {"interested": END, "rejected": "persist_refusal"})
        builder.add_edge("persist_refusal", END)
        self.graph = builder.compile()

    async def load_opinions(self, state: TopicGateState) -> dict[str, Any]:
        """并行读取双方观点记忆，只保留可公开且置信度足够的内容。"""
        async def load(user_id: str) -> list[dict[str, Any]]:
            context = await self._context_builder(user_id, "相关观点", conversation_id=None)
            values = ((context or {}).get("retrieved_memories") or {}).get("opinions", [])
            threshold = float(os.getenv("DIALOGUE_OPINION_CONFIDENCE_THRESHOLD", "0.60"))
            return [x for x in values if float(x.get("confidence") or 0) >= threshold and x.get("privacy", "private") != "sensitive"]

        import asyncio
        opinions_a, opinions_b = await asyncio.gather(load(state["user_id_a"]), load(state["user_id_b"]))
        return {"opinions_a": opinions_a, "opinions_b": opinions_b}

    async def find_shared_topics(self, state: TopicGateState) -> dict[str, Any]:
        """调用回答模型识别双方观点主题的重复部分。"""
        if not state.get("opinions_a") or not state.get("opinions_b"):
            return {"shared_topics": []}
        prompt = json.dumps({"task": "找出双方观点中主题相同或相关且值得讨论的部分，只返回JSON数组", "a": state["opinions_a"], "b": state["opinions_b"], "schema": [{"topic": "", "stance_a": "", "stance_b": "", "similarity": 0.0, "discussion_potential": 0.0}]}, ensure_ascii=False, default=str)
        response = await self._llm.generate(prompt, temperature=0, max_tokens=1000)
        try:
            data = json.loads(response.text)
            if isinstance(data, dict):
                data = data.get("topics", data.get("shared_topics", []))
            threshold = float(os.getenv("DIALOGUE_OPINION_SIMILARITY_THRESHOLD", "0.65"))
            result = []
            for item in data if isinstance(data, list) else []:
                similarity = float(item.get("similarity", 0))
                if similarity < threshold:
                    continue
                item = dict(item)
                item["score"] = round(0.45 * similarity + 0.55 * float(item.get("discussion_potential", 0.5)), 4)
                result.append(item)
            return {"shared_topics": sorted(result, key=lambda x: x["score"], reverse=True)}
        except (json.JSONDecodeError, TypeError, ValueError):
            return {"shared_topics": []}

    @staticmethod
    def _route_topic(state: TopicGateState) -> str:
        """根据是否存在共同观点选择话题来源。"""
        return "shared" if state.get("shared_topics") and state.get("topic_mode", "shared_first") == "shared_first" else "random"

    async def select_shared_topic(self, state: TopicGateState) -> dict[str, Any]:
        """选择评分最高的共同观点主题。"""
        item = state["shared_topics"][0]
        return {"current_topic": str(item.get("topic", "")), "topic_source": "shared_opinion"}

    async def select_random_topic(self, state: TopicGateState) -> dict[str, Any]:
        """从发起方观点或场景兜底话题中随机选择一个试探主题。"""
        candidates = [str(x.get("topic") or x.get("content", "")) for x in state.get("opinions_a", []) if x.get("topic") or x.get("content")]
        if not candidates:
            candidates = [f"聊聊{state.get('scene_id') or '最近生活中有趣的事情'}"]
        return {"current_topic": random.choice(candidates), "topic_source": "random_opinion" if state.get("opinions_a") else "scene"}

    async def ask_interest(self, state: TopicGateState) -> dict[str, Any]:
        """让 B 基于自己的上下文判断是否愿意讨论选定话题。"""
        context = await self._context_builder(state["user_id_b"], state["current_topic"], conversation_id=None)
        prompt = json.dumps({"task": "判断是否对话题感兴趣，只返回JSON", "topic": state["current_topic"], "context": context, "schema": {"interested": True, "score": 0.0, "reason": "", "response": ""}}, ensure_ascii=False, default=str)
        try:
            data = json.loads((await self._llm.generate(prompt, temperature=0, max_tokens=300)).text)
            score = float(data.get("score", 0))
            if not 0 <= score <= 1:
                raise ValueError
            interested = score >= float(os.getenv("DIALOGUE_INTEREST_THRESHOLD", "0.55"))
            return {"interest_score": score, "interest_decision": "interested" if interested else "rejected", "interest_reason": str(data.get("reason", "")), "refusal_response": str(data.get("response") or "这个话题我平时关注不多，暂时不太想聊。")}
        except (json.JSONDecodeError, TypeError, ValueError):
            return {"interest_score": 0.0, "interest_decision": "rejected", "interest_reason": "模型未返回有效兴趣判断", "refusal_response": "这个话题我平时关注不多，暂时不太想聊。"}

    async def persist_refusal(self, state: TopicGateState) -> dict[str, Any]:
        """保留拒绝分支节点，实际消息由对话编排器统一落库。"""
        return {}

