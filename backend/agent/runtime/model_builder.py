"""LLM 构建器。

本模块负责从 ``backend/.env``（以及当前进程环境变量）读取模型配置，构造
OpenAI 兼容协议的 ``LLM`` 实例。业务层只需要调用 ``build_llm``，不需要在
代码中硬编码 API Key、服务 URL 或模型名称。
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from dotenv import dotenv_values

from agent.runtime.llm import LLM


BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _setting(name: str, values: dict[str, Any], default: str | None = None) -> str | None:
    """按环境变量优先、``backend/.env`` 次之的顺序读取配置。"""
    value = os.getenv(name)
    if value is None:
        value = values.get(name)
    if value is None or not str(value).strip():
        return default
    return str(value).strip()


def _post_chat_completion(model: str, prompt: str, options: dict[str, Any], *, api_key: str, base_url: str) -> dict[str, Any]:
    """向 OpenAI 兼容的 Chat Completions 接口发送同步请求。"""
    endpoint = base_url.rstrip("/") + "/chat/completions"
    system_prompt = str(options.pop("system_prompt", ""))
    messages = ([{"role": "system", "content": system_prompt}] if system_prompt else [])
    messages.append({"role": "user", "content": prompt})
    payload = {"model": model, "messages": messages, **options}
    request = Request(endpoint, data=json.dumps(payload).encode("utf-8"), headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(request, timeout=60) as response:  # noqa: S310 - URL 来自用户配置
            body = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"LLM 请求失败：{exc}") from exc
    choices = body.get("choices") or []
    if not choices or not choices[0].get("message", {}).get("content"):
        raise RuntimeError("LLM 返回结果缺少 choices[0].message.content")
    return {"text": choices[0]["message"]["content"], "model": body.get("model") or model, "usage": body.get("usage") or {}, "raw": body}


def build_llm(*, env_file: str | Path | None = None, model: str | None = None) -> LLM:
    """从配置文件构造 OpenAI 兼容的 ``LLM`` 实例。

    配置项：``LLM_API_KEY``、``LLM_BASE_URL``、``LLM_MODEL``。为兼容常见服务，
    也支持 ``OPENAI_API_KEY``、``OPENAI_BASE_URL`` 和 ``OPENAI_MODEL`` 别名。
    进程环境变量优先于 ``.env`` 文件；缺少 API Key 或模型时立即抛出明确异常。
    """
    path = Path(env_file) if env_file else BACKEND_ROOT / ".env"
    values = dotenv_values(path) if path.exists() else {}
    api_key = _setting("LLM_API_KEY", values) or _setting("OPENAI_API_KEY", values)
    base_url = _setting("LLM_BASE_URL", values) or _setting("OPENAI_BASE_URL", values, "https://api.openai.com/v1")
    model_name = model or _setting("LLM_MODEL", values) or _setting("OPENAI_MODEL", values)
    if not api_key:
        raise ValueError(f"未配置 LLM_API_KEY 或 OPENAI_API_KEY，请在 {path} 中设置")
    if not model_name:
        raise ValueError(f"未配置 LLM_MODEL 或 OPENAI_MODEL，请在 {path} 中设置")
    assert base_url is not None

    def requester(selected_model: str, prompt: str, options: dict[str, Any]) -> dict[str, Any]:
        """将 LLM 请求转发到配置的 OpenAI 兼容服务。"""
        return _post_chat_completion(selected_model, prompt, dict(options), api_key=api_key, base_url=base_url)

    return LLM(model_name, requester)


def build_evaluator_llm(*, env_file: str | Path | None = None, model: str | None = None) -> LLM:
    """读取独立评判模型配置并创建 LLM，不自动复用回答模型配置。"""
    path = Path(env_file) if env_file else BACKEND_ROOT / ".env"
    values = dotenv_values(path) if path.exists() else {}
    api_key = _setting("EVALUATOR_LLM_API_KEY", values)
    base_url = _setting("EVALUATOR_LLM_BASE_URL", values)
    model_name = model or _setting("EVALUATOR_LLM_MODEL", values)
    if not api_key or not model_name:
        raise ValueError(f"未完整配置 EVALUATOR_LLM_API_KEY、EVALUATOR_LLM_BASE_URL、EVALUATOR_LLM_MODEL，请在 {path} 中设置")
    if not base_url:
        base_url = "https://api.openai.com/v1"

    def requester(selected_model: str, prompt: str, options: dict[str, Any]) -> dict[str, Any]:
        """将评判请求转发到独立的 OpenAI 兼容服务。"""
        return _post_chat_completion(selected_model, prompt, dict(options), api_key=api_key, base_url=base_url)

    return LLM(model_name, requester)


async def build_llm_async(*, env_file: str | Path | None = None, model: str | None = None) -> LLM:
    """提供异步构建入口，保持与异步 Agent 初始化流程一致。"""
    return await asyncio.to_thread(build_llm, env_file=env_file, model=model)
