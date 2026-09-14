"""数字分身场景匹配策略。"""
from __future__ import annotations

import json
import random
import inspect
from typing import Any, Awaitable, Callable, Literal

from agent.runtime.llm import LLM


class AvatarMatcher:
    """在注入的候选提供器上实现随机、手动和 LLM 匹配。"""

    def __init__(self, candidate_provider: Callable[[str], Awaitable[list[dict[str, Any]]] | list[dict[str, Any]]], llm: LLM | None = None) -> None:
        """注入场景候选读取函数和可选匹配模型。"""
        self._provider = candidate_provider
        self._llm = llm

    async def match(self, avatar_id: str, scene_id: str, mode: Literal["llm", "random", "manual"], target_avatar_id: str | None = None) -> dict[str, Any]:
        """按照指定模式返回一个空闲候选。"""
        # PresenceService.list_candidates is intentionally synchronous (it owns a
        # short-lived PostgreSQL connection), while some deployments inject an
        # async provider.  Normalize both forms here so matching never attempts
        # to ``await`` a plain list.
        provided = self._provider(scene_id)
        candidates_raw = await provided if inspect.isawaitable(provided) else provided
        candidates = [x for x in (candidates_raw or []) if str(x.get("avatar_id")) != avatar_id and x.get("status", "idle") == "idle"]
        if mode == "manual":
            found = next((x for x in candidates if str(x.get("avatar_id")) == str(target_avatar_id)), None)
            if not found:
                raise ValueError("目标数字分身不存在或当前不可用")
            return found
        if not candidates:
            raise ValueError("当前场景没有空闲数字分身")
        if mode == "random" or not self._llm:
            return random.choice(candidates)
        prompt = json.dumps({"task": "从候选数字分身中选择最适合聊天的一位，只返回avatar_id", "candidates": candidates}, ensure_ascii=False, default=str)
        result = await self._llm.generate(prompt, temperature=0, max_tokens=100)
        wanted = result.text.strip().strip('`"')
        return next((x for x in candidates if str(x.get("avatar_id")) == wanted), candidates[0])

