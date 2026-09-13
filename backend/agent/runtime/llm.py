"""大语言模型调用抽象。

本模块不绑定具体厂商 SDK。调用方可以注入 HTTP、OpenAI 兼容客户端或测试函数，
由 ``LLM`` 统一提供异步文本生成接口。这样 Agent 不需要知道模型供应商的请求格式。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Mapping


LLMRequester = Callable[[str, str, Mapping[str, Any]], Awaitable[str] | str]


@dataclass(frozen=True)
class LLMResponse:
    """模型调用结果，保留回答文本和请求级元数据。"""

    text: str
    model: str
    usage: Mapping[str, Any] = field(default_factory=dict)
    request_id: str | None = None
    raw: Mapping[str, Any] | None = None


class LLM:
    """统一的大语言模型客户端。

    ``requester`` 是一个由应用层注入的请求函数，参数依次为模型名、Prompt 和
    生成参数。LLM 类只负责参数校验、同步函数异步化和结果标准化，不负责检索、
    Prompt 业务拼接或 Agent 决策。
    """

    def __init__(
        self,
        model: str,
        requester: LLMRequester,
        *,
        default_temperature: float = 0.2,
        default_max_tokens: int = 1200,
    ) -> None:
        """创建模型客户端并保存默认生成参数。"""
        if not model.strip():
            raise ValueError("model 不能为空")
        if not 0 <= default_temperature <= 2:
            raise ValueError("default_temperature 必须在 0 到 2 之间")
        if default_max_tokens <= 0:
            raise ValueError("default_max_tokens 必须大于 0")
        self.model = model
        self._requester = requester
        self.default_temperature = default_temperature
        self.default_max_tokens = default_max_tokens

    async def generate(
        self,
        prompt: str,
        *,
        system_prompt: str = "",
        temperature: float | None = None,
        max_tokens: int | None = None,
        request_id: str | None = None,
        **parameters: Any,
    ) -> LLMResponse:
        """调用模型生成文本，并将结果标准化为 ``LLMResponse``。

        关键逻辑：请求函数既可以是异步函数，也可以是普通同步函数；同步函数会
        在线程中执行，避免阻塞 Agent 的异步事件循环。
        """
        if not prompt.strip():
            raise ValueError("prompt 不能为空")
        actual_temperature = self.default_temperature if temperature is None else temperature
        actual_max_tokens = self.default_max_tokens if max_tokens is None else max_tokens
        if not 0 <= actual_temperature <= 2:
            raise ValueError("temperature 必须在 0 到 2 之间")
        if actual_max_tokens <= 0:
            raise ValueError("max_tokens 必须大于 0")
        options = {"temperature": actual_temperature, "max_tokens": actual_max_tokens, **parameters}
        # 同步请求函数放入线程执行，异步请求函数直接等待，避免阻塞事件循环。
        request_args = (self.model, prompt, {"system_prompt": system_prompt, **options})
        if asyncio.iscoroutinefunction(self._requester):
            result = await self._requester(*request_args)
        else:
            result = await asyncio.to_thread(self._requester, *request_args)
        if isinstance(result, LLMResponse):
            return result
        if isinstance(result, str):
            return LLMResponse(text=result, model=self.model, request_id=request_id)
        if isinstance(result, Mapping):
            text = str(result.get("text") or result.get("content") or "")
            if not text.strip():
                raise ValueError("模型返回结果缺少 text/content")
            return LLMResponse(
                text=text,
                model=str(result.get("model") or self.model),
                usage=result.get("usage") or {},
                request_id=str(result.get("request_id") or request_id) if result.get("request_id") or request_id else None,
                raw=result,
            )
        raise TypeError("requester 必须返回字符串、Mapping 或 LLMResponse")
