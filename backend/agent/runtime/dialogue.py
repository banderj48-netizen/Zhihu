"""双数字分身交替对话编排。"""
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Any
from uuid import uuid4
from psycopg.types.json import Jsonb

from agent.adapters.vector_search import VectorSearchAdapter
from agent.profile.chat_repository import ChatRepository
from agent.profile.langgraph_tools import create_behavior_memory_tool
from agent.runtime.agent_graph import DigitalTwinAgentGraph, AgentTurnState
from agent.runtime.evaluator import DialogueEvaluation, DialogueEvaluator
from agent.runtime.llm import LLM
from agent.runtime.push_gateway import MatchPushGateway


@dataclass(frozen=True)
class DialogueResult:
    """双 Agent 对话执行结果。"""
    dialogue_run_id: str
    conversation_id: str
    status: str
    rounds: int
    evaluation: DialogueEvaluation | None = None


class DialogueConcurrencyLimiter:
    """限制单进程同时运行的双 Agent 对话数量。"""

    def __init__(self, max_num: int = 10) -> None:
        """创建并发信号量。"""
        self._semaphore = asyncio.Semaphore(max_num)

    async def acquire(self) -> None:
        """等待可用对话名额。"""
        await self._semaphore.acquire()

    def release(self) -> None:
        """释放一个对话名额。"""
        self._semaphore.release()


async def run_agent_dialogue(avatar_a_id: str, avatar_b_id: str, *, user_id_a: str, user_id_b: str, initial_question: str, llm_a: LLM, llm_b: LLM, context_builder: Any, chat_repository: ChatRepository, vector_store: VectorSearchAdapter | None = None, evaluator: DialogueEvaluator | None = None, push_gateway: MatchPushGateway | None = None, max_rounds: int = 10, limiter: DialogueConcurrencyLimiter | None = None) -> DialogueResult:
    """执行 A 提问→B 回答→B 提问→A 回答，并持久化双方消息。"""
    if avatar_a_id == avatar_b_id: raise ValueError("两个 Agent 必须使用不同 avatar_id")
    max_rounds = max(1, min(max_rounds, 10))
    limiter = limiter or DialogueConcurrencyLimiter(int(os.getenv("MAX_AGENT_DIALOGUES", "10")))
    await limiter.acquire()
    run_id, conversation_id = str(uuid4()), chat_repository.create_conversation("direct", "数字分身对话")
    _update_run(run_id, conversation_id, avatar_a_id, avatar_b_id, user_id_a, user_id_b, "running", 0, max_rounds)
    try:
        participant_a = _participant_id(chat_repository, conversation_id, avatar_a_id, "Agent A")
        participant_b = _participant_id(chat_repository, conversation_id, avatar_b_id, "Agent B")
        graph_a = DigitalTwinAgentGraph(llm_a, context_builder, [create_behavior_memory_tool(user_id_a, avatar_a_id, None)]).graph
        graph_b = DigitalTwinAgentGraph(llm_b, context_builder, [create_behavior_memory_tool(user_id_b, avatar_b_id, None)]).graph
        transcript: list[dict[str, Any]] = []
        question = initial_question
        for round_no in range(1, max_rounds + 1):
            answer_b = await _run_turn(graph_b, user_id_b, avatar_b_id, conversation_id, question, round_no)
            await _persist(chat_repository, vector_store, conversation_id, participant_b, answer_b, run_id, "B", round_no)
            transcript.append({"role": "B", "content": answer_b})
            question = answer_b
            answer_a = await _run_turn(graph_a, user_id_a, avatar_a_id, conversation_id, question, round_no)
            await _persist(chat_repository, vector_store, conversation_id, participant_a, answer_a, run_id, "A", round_no)
            transcript.append({"role": "A", "content": answer_a})
            question = answer_a
        _update_run(run_id, conversation_id, avatar_a_id, avatar_b_id, user_id_a, user_id_b, "evaluating", max_rounds, max_rounds)
        evaluation = await evaluator.evaluate(transcript) if evaluator else None
        if evaluation:
            _save_evaluation(run_id, evaluation)
        _update_run(run_id, conversation_id, avatar_a_id, avatar_b_id, user_id_a, user_id_b, "completed", max_rounds, max_rounds)
        if evaluation and push_gateway and evaluation.score > float(os.getenv("GREAT_SCORE", "0.8")):
            await push_gateway.push_profile_urls(user_id_a, user_id_b, None, None, evaluation.score)
        return DialogueResult(run_id, conversation_id, "completed", max_rounds, evaluation)
    except Exception:
        try:
            _update_run(run_id, conversation_id, avatar_a_id, avatar_b_id, user_id_a, user_id_b, "failed", 0, max_rounds)
        finally:
            raise
    finally:
        limiter.release()


def _update_run(run_id: str, conversation_id: str, avatar_a_id: str, avatar_b_id: str, user_a: str, user_b: str, status: str, current_turn: int, max_rounds: int) -> None:
    """写入双 Agent 运行状态；失败不影响已完成的聊天事实。"""
    from db.database import connect
    with connect() as db:
        db.execute("""INSERT INTO agent_dialogue_runs(id,conversation_id,avatar_a_id,avatar_b_id,user_a_id,user_b_id,status,current_turn,max_rounds,started_at)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,now())
            ON CONFLICT(id) DO UPDATE SET status=EXCLUDED.status,current_turn=EXCLUDED.current_turn,ended_at=CASE WHEN EXCLUDED.status IN ('completed','failed','cancelled') THEN now() ELSE agent_dialogue_runs.ended_at END""",
            (run_id, conversation_id, avatar_a_id, avatar_b_id, user_a, user_b, status, current_turn, max_rounds))


def _save_evaluation(run_id: str, evaluation: DialogueEvaluation) -> None:
    """将评判结果保存到业务评判表。"""
    from db.database import connect
    with connect() as db:
        db.execute("""INSERT INTO agent_dialogue_evaluations(dialogue_run_id,evaluator_model,score,great_score,summary,dimensions,raw_result)
            VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(dialogue_run_id) DO UPDATE SET score=EXCLUDED.score,summary=EXCLUDED.summary,dimensions=EXCLUDED.dimensions,raw_result=EXCLUDED.raw_result""",
            (run_id, "evaluator", evaluation.score, float(os.getenv("GREAT_SCORE", "0.8")), evaluation.summary, Jsonb(dict(evaluation.dimensions)), Jsonb(dict(evaluation.raw_result))))


def _participant_id(repository: ChatRepository, conversation_id: str, avatar_id: str, name: str) -> str:
    """创建参与者并返回参与者 ID。"""
    from db.database import connect
    with connect() as db:
        row = db.execute("INSERT INTO chat_participants(conversation_id,avatar_id,display_name) VALUES(%s,%s,%s) RETURNING id", (conversation_id, avatar_id, name)).fetchone()
        return str(row["id"])


async def _run_turn(graph: Any, user_id: str, avatar_id: str, conversation_id: str, question: str, turn_no: int) -> str:
    """执行一个 Agent 图回合并返回文本回答。"""
    result = await graph.ainvoke(AgentTurnState(avatar_id=avatar_id, user_id=user_id, conversation_id=conversation_id, question=question, messages=[], turn_no=turn_no))
    return str(result.get("last_answer") or "")


async def _persist(repository: ChatRepository, vector_store: VectorSearchAdapter | None, conversation_id: str, participant_id: str, content: str, run_id: str, role: str, turn_no: int) -> None:
    """先写 PostgreSQL，再尽力写 Chroma；向量失败不影响聊天事实记录。"""
    result = repository.append_message(conversation_id, participant_id, content, metadata={"dialogue_run_id": run_id, "agent_role": role, "turn_no": turn_no})
    if vector_store:
        try:
            await vector_store.upsert("chat_messages", [result["message_id"]], [content], [{"message_id": result["message_id"], "conversation_id": conversation_id, "agent_role": role, "turn_no": turn_no, "deleted": False}])
        except Exception:
            # PostgreSQL 是事实源；Chroma 失败时由上层同步任务重试。
            pass
