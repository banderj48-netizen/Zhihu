"""双数字分身交替对话编排。"""
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Any, Awaitable, Callable
from uuid import uuid4
from psycopg.types.json import Jsonb

from agent.adapters.vector_search import VectorSearchAdapter
from agent.profile.chat_repository import ChatRepository
from agent.profile.langgraph_tools import create_behavior_memory_tool
from agent.runtime.agent_graph import DigitalTwinAgentGraph, AgentTurnState
from agent.runtime.evaluator import DialogueEvaluation, DialogueEvaluator
from agent.runtime.llm import LLM
from agent.runtime.push_gateway import MatchPushGateway
from agent.runtime.topic_gate import TopicGateGraph, TopicGateState


@dataclass(frozen=True)
class DialogueResult:
    """双 Agent 对话执行结果。"""
    dialogue_run_id: str
    conversation_id: str
    chat_no: str
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


async def run_agent_dialogue(avatar_a_id: str, avatar_b_id: str, *, user_id_a: str, user_id_b: str, initial_question: str | None = None, scene_id: str = "", topic_mode: str = "shared_first", llm_a: LLM, llm_b: LLM, context_builder: Any, chat_repository: ChatRepository, vector_store: VectorSearchAdapter | None = None, evaluator: DialogueEvaluator | None = None, push_gateway: MatchPushGateway | None = None, max_rounds: int = 10, limiter: DialogueConcurrencyLimiter | None = None, event_callback: Callable[[dict[str, Any]], Awaitable[None] | None] | None = None, cancel_event: asyncio.Event | None = None, dialogue_run_id: str | None = None) -> DialogueResult:
    """执行 A 提问→B 回答→B 提问→A 回答，并持久化双方消息。"""
    if avatar_a_id == avatar_b_id: raise ValueError("两个 Agent 必须使用不同 avatar_id")
    max_rounds = max(1, min(max_rounds, 10))
    limiter = limiter or DialogueConcurrencyLimiter(int(os.getenv("MAX_AGENT_DIALOGUES", "10")))
    await limiter.acquire()
    async def emit(event: str, **payload: Any) -> None:
        """向实时订阅者发布事件；回调失败不影响对话事实。"""
        if event_callback is None:
            return
        data = {"event": event, "run_id": run_id, "round": payload.pop("round", 0), "max_rounds": max_rounds, "status": payload.pop("status", "running"), "payload": payload}
        try:
            value = event_callback(data)
            if asyncio.iscoroutine(value):
                await value
        except Exception:
            pass

    async def check_cancel() -> None:
        """在每个半轮前检查取消信号并抛出可识别异常。"""
        if cancel_event is not None and cancel_event.is_set():
            raise asyncio.CancelledError()
    run_id, conversation_id = dialogue_run_id or str(uuid4()), chat_repository.create_conversation("direct", "数字分身对话")
    _update_run(run_id, conversation_id, avatar_a_id, avatar_b_id, user_id_a, user_id_b, "running", 0, max_rounds)
    chat_no = _create_chat_group(run_id, conversation_id, avatar_a_id, avatar_b_id, user_id_a, user_id_b, {"scene_id": scene_id, "topic_mode": topic_mode})
    try:
        await emit("run_started", status="running", payload={"avatar_a_id": avatar_a_id, "avatar_b_id": avatar_b_id, "scene_id": scene_id})
        participant_a = _participant_id(chat_repository, conversation_id, avatar_a_id, "Agent A")
        participant_b = _participant_id(chat_repository, conversation_id, avatar_b_id, "Agent B")
        graph_a = DigitalTwinAgentGraph(llm_a, context_builder, [create_behavior_memory_tool(user_id_a, avatar_a_id, None)]).graph
        graph_b = DigitalTwinAgentGraph(llm_b, context_builder, [create_behavior_memory_tool(user_id_b, avatar_b_id, None)]).graph
        transcript: list[dict[str, Any]] = []
        completed_rounds = 0
        gate = await TopicGateGraph(llm_a, context_builder).graph.ainvoke(TopicGateState(avatar_a_id=avatar_a_id, avatar_b_id=avatar_b_id, user_id_a=user_id_a, user_id_b=user_id_b, scene_id=scene_id, topic_mode=topic_mode)) if initial_question is None else {"current_topic": initial_question, "topic_source": "manual"}
        topic = str(gate.get("current_topic") or initial_question or "")
        await emit("topic_selected", topic=topic, topic_source=gate.get("topic_source"), score=(gate.get("shared_topics") or [{}])[0].get("score"))
        if gate.get("interest_decision") == "rejected":
            refusal = str(gate.get("refusal_response") or "这个话题我平时关注不多，暂时不太想聊。")
            await _persist(chat_repository, vector_store, conversation_id, participant_b, refusal, run_id, "B", 0, metadata={"event": "topic_rejected", "topic": topic, "interest_score": gate.get("interest_score", 0), "threshold": float(os.getenv("DIALOGUE_INTEREST_THRESHOLD", "0.55")), "reason": gate.get("interest_reason", "")})
            _update_run(run_id, conversation_id, avatar_a_id, avatar_b_id, user_id_a, user_id_b, "completed", 0, max_rounds, {"scene_id": scene_id, "selected_topic": topic, "termination_reason": "topic_rejected", "interest_check": gate})
            _update_chat_group(chat_no, "completed", {"termination_reason": "topic_rejected"})
            await emit("status", status="completed", termination_reason="topic_rejected")
            return DialogueResult(run_id, conversation_id, chat_no, "completed", 0, None)
        # 由 A 先围绕选定主题发起自然开场，再交给 B 回答。
        await check_cancel()
        opening = await _run_turn(graph_a, user_id_a, avatar_a_id, conversation_id, f"请在{scene_id or '当前场景'}自然开启关于‘{topic}’的闲聊，只输出一句话。", 0)
        await _persist(chat_repository, vector_store, conversation_id, participant_a, opening, run_id, "A", 0, metadata={"event": "topic_opening", "topic_source": gate.get("topic_source", "manual"), "topic": topic, "topic_score": (gate.get("shared_topics") or [{}])[0].get("score")})
        await emit("message", round=0, speaker="A", content=opening)
        transcript.append({"role": "A", "content": opening})
        question = opening
        for round_no in range(1, max_rounds + 1):
            await check_cancel()
            answer_b = await _run_turn(graph_b, user_id_b, avatar_b_id, conversation_id, question, round_no)
            await _persist(chat_repository, vector_store, conversation_id, participant_b, answer_b, run_id, "B", round_no)
            await emit("message", round=round_no, speaker="B", content=answer_b)
            await emit("round_progress", round=round_no, completed_messages=len(transcript) + 1)
            transcript.append({"role": "B", "content": answer_b})
            question = answer_b
            completed_rounds = round_no
            if _is_end_intent(answer_b):
                break
            # 开场消息已经计入 A 的首条消息；最后一轮只保留 B 的回答，确保总消息数不超过20条。
            if round_no < max_rounds:
                await check_cancel()
                answer_a = await _run_turn(graph_a, user_id_a, avatar_a_id, conversation_id, question, round_no)
                await _persist(chat_repository, vector_store, conversation_id, participant_a, answer_a, run_id, "A", round_no)
                await emit("message", round=round_no, speaker="A", content=answer_a)
                transcript.append({"role": "A", "content": answer_a})
                question = answer_a
                if _is_end_intent(answer_a):
                    break
        _update_run(run_id, conversation_id, avatar_a_id, avatar_b_id, user_id_a, user_id_b, "evaluating", completed_rounds, max_rounds)
        await emit("status", status="evaluating", round=completed_rounds)
        evaluation = None
        evaluation_failed = False
        if evaluator:
            try:
                evaluation = await evaluator.evaluate(transcript)
                _save_evaluation(run_id, evaluation)
            except Exception:
                # 评判失败不应回滚已经完成的聊天事实；运行仍可正常结束但不推送。
                evaluation_failed = True
        _update_run(run_id, conversation_id, avatar_a_id, avatar_b_id, user_id_a, user_id_b, "evaluation_failed" if evaluation_failed else "completed", completed_rounds, max_rounds, {"evaluation_failed": evaluation_failed})
        if evaluation and push_gateway and evaluation.score > float(os.getenv("GREAT_SCORE", "0.8")):
            await push_gateway.push_profile_urls(user_id_a, user_id_b, None, None, evaluation.score)
        _update_chat_group(chat_no, "completed", {})
        await emit("evaluation", score=evaluation.score if evaluation else None)
        await emit("status", status="evaluation_failed" if evaluation_failed else "completed")
        return DialogueResult(run_id, conversation_id, chat_no, "evaluation_failed" if evaluation_failed else "completed", completed_rounds, evaluation)
    except asyncio.CancelledError:
        _update_run(run_id, conversation_id, avatar_a_id, avatar_b_id, user_id_a, user_id_b, "cancelled", 0, max_rounds)
        _update_chat_group(chat_no, "cancelled", {"termination_reason": "cancelled"})
        await emit("status", status="cancelled", termination_reason="cancelled")
        return DialogueResult(run_id, conversation_id, chat_no, "cancelled", 0, None)
    except Exception:
        try:
            _update_run(run_id, conversation_id, avatar_a_id, avatar_b_id, user_id_a, user_id_b, "failed", 0, max_rounds)
            _update_chat_group(chat_no, "failed", {})
            await emit("error", status="failed", message="对话执行失败")
        finally:
            raise
    finally:
        limiter.release()


def _update_run(run_id: str, conversation_id: str, avatar_a_id: str, avatar_b_id: str, user_a: str, user_b: str, status: str, current_turn: int, max_rounds: int, metadata: dict[str, Any] | None = None) -> None:
    """写入双 Agent 运行状态；失败不影响已完成的聊天事实。"""
    from db.database import connect
    with connect() as db:
        db.execute("""INSERT INTO agent_dialogue_runs(id,conversation_id,avatar_a_id,avatar_b_id,user_a_id,user_b_id,status,current_turn,max_rounds,started_at,metadata)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,now(),%s)
            ON CONFLICT(id) DO UPDATE SET status=EXCLUDED.status,current_turn=EXCLUDED.current_turn,metadata=agent_dialogue_runs.metadata || EXCLUDED.metadata,ended_at=CASE WHEN EXCLUDED.status IN ('completed','failed','cancelled') THEN now() ELSE agent_dialogue_runs.ended_at END""",
            (run_id, conversation_id, avatar_a_id, avatar_b_id, user_a, user_b, status, current_turn, max_rounds, Jsonb(metadata or {})))


def _save_evaluation(run_id: str, evaluation: DialogueEvaluation) -> None:
    """将评判结果保存到业务评判表。"""
    from db.database import connect
    with connect() as db:
        db.execute("""INSERT INTO agent_dialogue_evaluations(dialogue_run_id,evaluator_model,score,great_score,summary,dimensions,raw_result)
            VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(dialogue_run_id) DO UPDATE SET score=EXCLUDED.score,summary=EXCLUDED.summary,dimensions=EXCLUDED.dimensions,raw_result=EXCLUDED.raw_result""",
            (run_id, "evaluator", evaluation.score, float(os.getenv("GREAT_SCORE", "0.8")), evaluation.summary, Jsonb(dict(evaluation.dimensions)), Jsonb(dict(evaluation.raw_result))))


def _create_chat_group(run_id: str, conversation_id: str, avatar_a: str, avatar_b: str, user_a: str, user_b: str, metadata: dict[str, Any]) -> str:
    """创建一次运行对应的唯一聊天组，并返回对外聊天号。"""
    from db.database import connect
    chat_no = f"chat_{uuid4().hex}"
    with connect() as db:
        row = db.execute("""INSERT INTO agent_chat_groups(chat_no,dialogue_run_id,conversation_id,initiator_avatar_id,invited_avatar_id,initiator_user_id,invited_user_id,metadata)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(dialogue_run_id) DO UPDATE SET metadata=agent_chat_groups.metadata || EXCLUDED.metadata RETURNING chat_no""", (chat_no, run_id, conversation_id, avatar_a, avatar_b, user_a, user_b, Jsonb(metadata))).fetchone()
        return str(row["chat_no"])


def _update_chat_group(chat_no: str, status: str, metadata: dict[str, Any]) -> None:
    """更新聊天组状态、结束时间和扩展元数据。"""
    from db.database import connect
    with connect() as db:
        # 终态消息已经全部写入 PostgreSQL 后才将聊天组标记为 ready/可见。
        processing_status = "failed" if status == "failed" else ("ready" if status in {"completed", "cancelled"} else "processing")
        db.execute("""UPDATE agent_chat_groups
            SET status=%s,
                ended_at=CASE WHEN %s <> 'running' THEN COALESCE(ended_at,now()) ELSE ended_at END,
                processing_status=%s,
                processed_at=CASE WHEN %s IN ('completed','cancelled','failed') THEN COALESCE(processed_at,now()) ELSE processed_at END,
                visible_at=CASE WHEN %s IN ('completed','cancelled') THEN COALESCE(visible_at,now()) ELSE visible_at END,
                metadata=metadata || %s
            WHERE chat_no=%s""", (status, status, processing_status, status, status, Jsonb(metadata), chat_no))


def _participant_id(repository: ChatRepository, conversation_id: str, avatar_id: str, name: str) -> str:
    """创建参与者并返回参与者 ID。"""
    from db.database import connect
    with connect() as db:
        row = db.execute("INSERT INTO chat_participants(conversation_id,avatar_id,display_name) VALUES(%s,%s,%s) RETURNING id", (conversation_id, avatar_id, name)).fetchone()
        return str(row["id"])


def _is_end_intent(text: str) -> bool:
    """识别模型自然表达的结束意图，避免继续生成无意义轮次。"""
    normalized = text.strip().lower()
    return any(mark in normalized for mark in ("再见", "先聊到这里", "下次再聊", "结束对话"))


async def _run_turn(graph: Any, user_id: str, avatar_id: str, conversation_id: str, question: str, turn_no: int) -> str:
    """执行一个 Agent 图回合并返回文本回答。"""
    result = await graph.ainvoke(AgentTurnState(avatar_id=avatar_id, user_id=user_id, conversation_id=conversation_id, question=question, messages=[], turn_no=turn_no))
    return str(result.get("last_answer") or "")


async def _persist(repository: ChatRepository, vector_store: VectorSearchAdapter | None, conversation_id: str, participant_id: str, content: str, run_id: str, role: str, turn_no: int, metadata: dict[str, Any] | None = None) -> None:
    """先写 PostgreSQL，再尽力写 Chroma；向量失败不影响聊天事实记录。"""
    result = repository.append_message(conversation_id, participant_id, content, metadata={"dialogue_run_id": run_id, "agent_role": role, "turn_no": turn_no, **(metadata or {})})
    from db.database import connect
    with connect() as db:
        db.execute("UPDATE agent_chat_groups SET message_count=message_count+1 WHERE dialogue_run_id=%s", (run_id,))
    if vector_store:
        try:
            await vector_store.upsert("chat_messages", [result["message_id"]], [content], [{"message_id": result["message_id"], "conversation_id": conversation_id, "agent_role": role, "turn_no": turn_no, "deleted": False}])
        except Exception:
            # PostgreSQL 是事实源；Chroma 失败时由上层同步任务重试。
            pass
