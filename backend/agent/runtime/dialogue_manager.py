"""双 Agent 后台运行管理与 SSE 事件缓冲。"""
from __future__ import annotations

import asyncio
from dataclasses import asdict
from typing import Any, Awaitable, Callable
from uuid import uuid4

from agent.runtime.dialogue import DialogueConcurrencyLimiter, DialogueResult
from agent.runtime.presence import PresenceService


Runner = Callable[..., Awaitable[DialogueResult]]


class DialogueManager:
    """统一管理后台任务、取消信号、并发名额和短期事件历史。"""

    def __init__(self, runner: Runner, *, max_dialogues: int = 10, presence: PresenceService | None = None) -> None:
        """注入对话执行函数，避免管理器自行创建模型或数据库连接。"""
        self.runner = runner
        self.limiter = DialogueConcurrencyLimiter(max_dialogues)
        self.presence = presence or PresenceService()
        self.tasks: dict[str, asyncio.Task[DialogueResult]] = {}
        self.cancel_events: dict[str, asyncio.Event] = {}
        self.events: dict[str, list[dict[str, Any]]] = {}
        self.waiters: dict[str, list[asyncio.Queue[dict[str, Any]]]] = {}
        self.results: dict[str, DialogueResult] = {}

    async def start(self, **kwargs: Any) -> str:
        """创建后台任务并立即返回运行 ID。"""
        run_id = str(kwargs.pop("run_id", None) or uuid4())
        cancel_event = asyncio.Event()
        self.cancel_events[run_id] = cancel_event
        self.events[run_id] = []
        self.waiters[run_id] = []
        kwargs["limiter"] = self.limiter
        kwargs["dialogue_run_id"] = run_id
        kwargs["event_callback"] = lambda event: self.publish(run_id, event)
        kwargs["cancel_event"] = cancel_event
        task = asyncio.create_task(self._run(run_id, kwargs))
        self.tasks[run_id] = task
        await self.publish(run_id, {"event": "run_started", "run_id": run_id, "round": 0, "max_rounds": kwargs.get("max_rounds", 10), "status": "queued", "payload": {}})
        return run_id

    async def _run(self, run_id: str, kwargs: dict[str, Any]) -> DialogueResult:
        """执行单次对话并在终态释放场景占用。"""
        try:
            result = await self.runner(**kwargs)
            self.results[run_id] = result
            await self.publish(run_id, {"event": "status", "run_id": run_id, "round": result.rounds, "max_rounds": kwargs.get("max_rounds", 10), "status": result.status, "payload": {"chat_no": result.chat_no}})
            return result
        except asyncio.CancelledError:
            await self.publish(run_id, {"event": "status", "run_id": run_id, "round": 0, "max_rounds": kwargs.get("max_rounds", 10), "status": "cancelled", "payload": {}})
            raise
        except Exception as exc:
            await self.publish(run_id, {"event": "error", "run_id": run_id, "round": 0, "max_rounds": kwargs.get("max_rounds", 10), "status": "failed", "payload": {"message": str(exc)}})
            raise
        finally:
            scene_id = kwargs.get("scene_id") or ""
            if scene_id:
                # 在场表的当前运行外键可能在对话事务稍后才创建，因此预占时使用空外键；
                # 这里按 avatar+scene 释放，避免因外键尚未同步而残留 busy 状态。
                self.presence.release(str(kwargs.get("avatar_a_id")), scene_id)
                self.presence.release(str(kwargs.get("avatar_b_id")), scene_id)
            self.cancel_events.pop(run_id, None)

    async def publish(self, run_id: str, event: dict[str, Any]) -> None:
        """追加单调递增事件 ID，并广播给当前 SSE 订阅者。"""
        history = self.events.setdefault(run_id, [])
        item = dict(event)
        item.setdefault("run_id", run_id)
        item["event_id"] = f"event_{len(history) + 1:06d}"
        history.append(item)
        for queue in list(self.waiters.get(run_id, [])):
            await queue.put(item)

    def status(self, run_id: str) -> dict[str, Any]:
        """返回运行状态和最近事件，便于 SSE 断线后补齐。"""
        task = self.tasks.get(run_id)
        result = self.results.get(run_id)
        return {"run_id": run_id, "status": result.status if result else ("running" if task and not task.done() else "failed"), "result": asdict(result) if result else None, "events": list(self.events.get(run_id, []))}

    async def cancel(self, run_id: str) -> bool:
        """发送协作式取消信号，不强制杀死正在写入数据库的回合。"""
        event = self.cancel_events.get(run_id)
        if not event:
            return False
        event.set()
        await self.publish(run_id, {"event": "status", "run_id": run_id, "round": 0, "max_rounds": 10, "status": "cancelling", "payload": {}})
        return True

    async def subscribe(self, run_id: str, last_event_id: str | None = None):
        """以异步生成器方式提供历史事件和后续事件。"""
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        history = self.events.get(run_id)
        if history is None:
            return
        start = 0
        if last_event_id and last_event_id.startswith("event_"):
            try:
                start = int(last_event_id.rsplit("_", 1)[1])
            except ValueError:
                start = 0
        for item in history[start:]:
            yield item
        self.waiters.setdefault(run_id, []).append(queue)
        try:
            while True:
                item = await asyncio.wait_for(queue.get(), timeout=30)
                yield item
                if item.get("status") in {"completed", "evaluation_failed", "cancelled", "failed"} and item.get("event") in {"status", "error"}:
                    break
        except asyncio.TimeoutError:
            yield {"event": "status", "run_id": run_id, "event_id": f"event_{len(self.events.get(run_id, [])) + 1:06d}", "round": 0, "max_rounds": 10, "status": "heartbeat", "payload": {}}
        finally:
            if queue in self.waiters.get(run_id, []):
                self.waiters[run_id].remove(queue)
