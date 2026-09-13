"""LangGraph 单 Agent 图定义。"""
from __future__ import annotations

import json
from typing import Any, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from agent.runtime.llm import LLM


class AgentTurnState(TypedDict, total=False):
    """单次 Agent 回合的 LangGraph 状态。"""
    avatar_id: str
    user_id: str
    conversation_id: str
    question: str
    context: dict[str, Any]
    messages: list[Any]
    last_answer: str | None
    tool_calls: list[dict[str, Any]]
    used_memory_ids: list[str]
    evidence_refs: list[str]
    turn_no: int
    finished: bool


class DigitalTwinAgentGraph:
    """构建一个绑定单个数字分身的 LangGraph 执行图。"""

    def __init__(self, llm: LLM, context_builder: Any, tools: list[BaseTool] | None = None) -> None:
        """注入模型、上下文组装函数和可选工具。"""
        self.llm = llm
        self.context_builder = context_builder
        self.tools = tools or []
        self.graph = self._build_graph()

    def _build_graph(self) -> Any:
        """创建 prepare_context、call_model、ToolNode 和结束节点。"""
        builder = StateGraph(AgentTurnState)
        builder.add_node("prepare_context", self.prepare_context)
        builder.add_node("call_model", self.call_model)
        builder.add_node("execute_tools", ToolNode(self.tools) if self.tools else self.no_tools)
        builder.add_node("persist_answer", self.persist_answer)
        builder.add_edge(START, "prepare_context")
        builder.add_edge("prepare_context", "call_model")
        builder.add_conditional_edges("call_model", self.route_after_model, {"execute_tools": "execute_tools", "persist_answer": "persist_answer"})
        builder.add_edge("execute_tools", "prepare_context")
        builder.add_edge("persist_answer", END)
        return builder.compile()

    async def prepare_context(self, state: AgentTurnState) -> dict[str, Any]:
        """每次模型调用前重新读取当前数字分身上下文。"""
        context = await self.context_builder(state["user_id"], state["question"], conversation_id=state.get("conversation_id"))
        return {"context": context}

    async def call_model(self, state: AgentTurnState) -> dict[str, Any]:
        """将结构化上下文和消息交给 LLM，并识别可选工具调用。"""
        prompt = json.dumps({"context": state.get("context", {}), "messages": [getattr(x, "content", str(x)) for x in state.get("messages", [])], "question": state["question"]}, ensure_ascii=False, default=str)
        tool_schemas = []
        for tool in self.tools:
            schema = getattr(tool.args_schema, "model_json_schema", lambda: {})()
            tool_schemas.append({"type": "function", "function": {"name": tool.name, "description": tool.description, "parameters": schema}})
        response = await self.llm.generate(prompt, request_id=f"graph-{state.get('turn_no', 0)}", tools=tool_schemas)
        raw = response.raw or {}
        if isinstance(raw.get("raw"), dict):
            raw = raw["raw"]
        calls = raw.get("tool_calls", []) if isinstance(raw, dict) else []
        # 将结构化工具 schema 交给 LLM；模型返回 tool_calls 后再由 ToolNode 执行。
        message = AIMessage(content=response.text, tool_calls=calls) if calls else AIMessage(content=response.text)
        return {"messages": [*state.get("messages", []), message], "last_answer": response.text, "tool_calls": calls}

    @staticmethod
    def route_after_model(state: AgentTurnState) -> str:
        """有工具调用时进入 ToolNode，否则结束本轮。"""
        return "execute_tools" if state.get("tool_calls") else "persist_answer"

    async def no_tools(self, state: AgentTurnState) -> dict[str, Any]:
        """无工具配置时的安全降级节点。"""
        return {"tool_calls": []}

    async def persist_answer(self, state: AgentTurnState) -> dict[str, Any]:
        """结束当前图回合并保留模型回答。"""
        return {"finished": True}
