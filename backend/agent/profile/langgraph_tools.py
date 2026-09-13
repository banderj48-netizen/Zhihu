"""LangGraph 可调用的画像写入工具。"""
from __future__ import annotations

from typing import Any

from langchain_core.tools import StructuredTool

from .tools import propose_behavior_memory


def create_behavior_memory_tool(user_id: str, avatar_id: str, base_version_id: str | None) -> StructuredTool:
    """创建绑定用户和数字分身的行为记忆工具，模型不能修改绑定身份。"""

    def save_behavior_memory(topic: str, content: str, structured_data: dict[str, Any] | None = None, confidence: float | None = None) -> dict[str, Any]:
        """校验并提交行为记忆提案，始终以未确认状态写入。"""
        if not topic.strip() or not content.strip():
            raise ValueError("topic 和 content 不能为空")
        return propose_behavior_memory(
            user_id=user_id,
            avatar_id=avatar_id,
            base_version_id=base_version_id,
            topic=topic.strip(),
            content=content.strip(),
            structured_data=structured_data or {},
            level="middle",
            confidence=confidence,
            status="unconfirmed",
        )

    return StructuredTool.from_function(
        func=save_behavior_memory,
        name="save_behavior_memory",
        description="当对话观察到稳定的情境反应时，保存一条未确认的行为记忆提案。不能记录敏感属性或虚构事实。",
    )

