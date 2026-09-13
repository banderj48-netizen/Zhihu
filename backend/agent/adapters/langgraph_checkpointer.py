"""LangGraph PostgreSQL Checkpointer 构建辅助函数。"""
from __future__ import annotations

from typing import Any


def build_postgres_checkpointer(connection_string: str) -> Any:
    """创建 LangGraph PostgreSQL Checkpointer；具体建表由组件的 setup 完成。"""
    try:
        from langgraph.checkpoint.postgres import PostgresSaver
    except ImportError as exc:
        raise RuntimeError("请安装 langgraph-checkpoint-postgres") from exc
    saver = PostgresSaver.from_conn_string(connection_string)
    return saver

