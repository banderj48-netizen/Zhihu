"""真实 Embedding、混合检索和 Agent 上下文组装验收脚本。

脚本只通过现有适配器和 Agent 图执行测试，不新增接口，也不把 API Key 写入
输出。真实 Agent 图默认不绑定画像写入工具，因此本脚本不会因为测试回复而
修改行为记忆；画像、原始资料和聊天正文仍由 PostgreSQL 事实源提供。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any


REPORTS_DIR = Path(__file__).resolve().parent
BACKEND_ROOT = REPORTS_DIR.parent
REPOSITORY_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


DEFAULT_USER_ID = "xie"
DEFAULT_QUESTION = (
    "请结合我的技术教育兴趣、原始资料和过去讨论，说明技术如何改善学习效率，"
    "并明确区分原始事实、个人判断和不确定性。"
)


async def run_real_embedding_context_agent_test(
    *,
    user_id: str = DEFAULT_USER_ID,
    question: str = DEFAULT_QUESTION,
    model_env_file: str | Path | None = None,
    sync_limit: int = 200,
) -> dict[str, Any]:
    """执行一次真实 Embedding、混合检索和 Agent 回复测试并返回完整结果。

    关键流程：先用当前独立模型环境生成真实查询向量，再消费 PostgreSQL
    outbox，随后显式调用 ``build_context`` 组装上下文。最后把同一个上下文
    构建器注入 LangGraph Agent，让 Agent 再次组装上下文并调用真实 LLM。
    返回值包含检索候选、Agent 实际使用的完整上下文和最终回复，便于复现。
    """
    if not user_id.strip():
        raise ValueError("user_id 不能为空")
    if not question.strip():
        raise ValueError("question 不能为空")
    if sync_limit < 0:
        raise ValueError("sync_limit 不能小于 0")

    previous_model_env = os.environ.get("TWINLOOP_MODEL_ENV_FILE")
    if model_env_file is not None:
        os.environ["TWINLOOP_MODEL_ENV_FILE"] = str(Path(model_env_file).resolve())

    try:
        # 延迟导入保证调用方可以先设置 TWINLOOP_MODEL_ENV_FILE，再加载模型配置。
        from db.database import connect
        from agent.adapters.chroma_factory import create_chroma_vector_store, embedding_config
        from agent.profile.outbox import sync_pending
        from agent.retrieval.service import PostgresRetrievalRepository, build_context
        from agent.runtime.agent_graph import AgentTurnState, DigitalTwinAgentGraph
        from agent.runtime.model_builder import build_llm

        model_config = embedding_config()
        vector_store = create_chroma_vector_store()

        # 直接请求一次真实向量，验证模型、Key、URL 和返回维度都可用。
        query_vectors = vector_store.embedding_function.embed_query([question])
        if not query_vectors or not query_vectors[0]:
            raise RuntimeError("Embedding 返回空向量")
        embedding_result = {
            "model": model_config["model"],
            "base_url": model_config["base_url"],
            "dimension": len(query_vectors[0]),
            "input_length": len(question),
        }

        sync_result = {"processed": 0, "failed": 0}
        if sync_limit:
            sync_result = await sync_pending(vector_store, limit=sync_limit)

        repository = PostgresRetrievalRepository(connect)
        retrieval_context = await build_context(
            user_id,
            question,
            repository,
            vector_store,
        )
        if not retrieval_context.get("profile", {}).get("avatar_id"):
            raise RuntimeError("未找到当前用户的 active 数字分身画像")

        async def context_builder(
            current_user_id: str,
            current_question: str,
            *,
            conversation_id: str | None = None,
        ) -> dict[str, Any]:
            """为 Agent 显式组装固定画像和 PostgreSQL+Chroma 动态上下文。"""
            return await build_context(
                current_user_id,
                current_question,
                repository,
                vector_store,
                conversation_id=conversation_id,
            )

        llm = build_llm()
        avatar_id = str(retrieval_context["profile"]["avatar_id"])
        # 不绑定 save_behavior_memory，保证该验收脚本只验证读取和回答链路。
        agent_graph = DigitalTwinAgentGraph(llm, context_builder, tools=[]).graph
        agent_state = AgentTurnState(
            avatar_id=avatar_id,
            user_id=user_id,
            question=question,
            messages=[],
            previous_message=question,
            scene_id="test",
            turn_no=1,
        )
        agent_result = await agent_graph.ainvoke(agent_state)
        agent_context = agent_result.get("context") or retrieval_context
        reply = str(agent_result.get("last_answer") or "").strip()
        if not reply:
            raise RuntimeError("Agent 未返回文本回复")

        return {
            "embedding": embedding_result,
            "vector_sync": sync_result,
            "retrieval": {
                "query": retrieval_context.get("query"),
                "retrieval_meta": retrieval_context.get("retrieval_meta"),
                "retrieved_memories": retrieval_context.get("retrieved_memories"),
                "source_documents": retrieval_context.get("source_documents"),
                "chat_history": retrieval_context.get("chat_history"),
            },
            "context": agent_context,
            "agent": {
                "model": llm.model,
                "avatar_id": avatar_id,
                "reply": reply,
            },
        }
    finally:
        # 作为库函数调用时恢复调用方原有环境，命令行进程则自然退出。
        if previous_model_env is None:
            os.environ.pop("TWINLOOP_MODEL_ENV_FILE", None)
        else:
            os.environ["TWINLOOP_MODEL_ENV_FILE"] = previous_model_env


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """解析命令行参数；默认使用 xie 和一条真实中文测试问题。"""
    parser = argparse.ArgumentParser(description="真实 Embedding、检索和 Agent 上下文组装测试")
    parser.add_argument("--user-id", default=DEFAULT_USER_ID, help="用户 UUID 或 external_id，默认 xie")
    parser.add_argument("--question", default=DEFAULT_QUESTION, help="真实测试问题")
    parser.add_argument(
        "--model-env-file",
        default=str(BACKEND_ROOT / ".env.models"),
        help="独立模型环境文件，默认 backend/.env.models",
    )
    parser.add_argument("--sync-limit", type=int, default=200, help="本次最多同步多少条 outbox，默认 200")
    parser.add_argument("--output", type=Path, help="可选：将完整 JSON 结果写入 UTF-8 文件")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """运行测试并输出完整 JSON；失败时返回非零退出码。"""
    args = parse_args(argv)
    try:
        result = asyncio.run(
            run_real_embedding_context_agent_test(
                user_id=args.user_id,
                question=args.question,
                model_env_file=args.model_env_file,
                sync_limit=args.sync_limit,
            )
        )
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1

    payload = json.dumps({"ok": True, **result}, ensure_ascii=False, indent=2, default=str)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
        print(json.dumps({"ok": True, "output": str(args.output.resolve())}, ensure_ascii=False))
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
