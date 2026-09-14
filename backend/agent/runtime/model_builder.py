"""基于官方 OpenAI Python SDK 的 LLM 构建器。

本模块只负责读取配置并包装 SDK 客户端，业务层继续依赖 ``LLM`` 抽象，
因此不会改变 Agent、检索和对话编排的调用方式。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from openai import OpenAI

from agent.runtime.llm import LLM
from agent.runtime.model_config import is_placeholder, load_model_values, model_env_path, model_setting


def _post_chat_completion(client: OpenAI, model: str, prompt: str, options: dict[str, Any]) -> dict[str, Any]:
    """使用官方 SDK 调用 Chat Completions，并转换为项目内部响应格式。"""
    system_prompt = str(options.pop("system_prompt", ""))
    messages = ([{"role": "system", "content": system_prompt}] if system_prompt else [])
    messages.append({"role": "user", "content": prompt})
    try:
        response = client.chat.completions.create(model=model, messages=messages, **options)
    except Exception as exc:
        # 统一包装 SDK 网络、鉴权和服务端错误，避免上层依赖供应商异常类型。
        raise RuntimeError(f"LLM 请求失败：{exc}") from exc
    if not response.choices:
        raise RuntimeError("LLM 返回结果缺少 choices")
    message = response.choices[0].message
    content = message.content or ""
    tool_calls = [call.model_dump() for call in (message.tool_calls or [])]
    if not content and not tool_calls:
        raise RuntimeError("LLM 返回结果缺少 choices[0].message.content/tool_calls")
    usage = response.usage.model_dump() if response.usage else {}
    return {"text": content, "tool_calls": tool_calls, "model": response.model or model, "usage": usage, "raw": response.model_dump()}


def build_llm(*, env_file: str | Path | None = None, model: str | None = None) -> LLM:
    """从配置文件构造 OpenAI 兼容的 ``LLM`` 实例。

    配置项：``LLM_API_KEY``、``LLM_BASE_URL``、``LLM_MODEL``，统一从独立的
    ``backend/.env.models`` 读取。为兼容常见服务，也支持 ``OPENAI_*`` 别名。
    进程环境变量优先于模型环境文件；缺少 API Key 或模型时立即抛出明确异常。
    """
    path = model_env_path(env_file)
    values = load_model_values(path)
    api_key = model_setting("LLM_API_KEY", values) or model_setting("OPENAI_API_KEY", values)
    base_url = model_setting("LLM_BASE_URL", values) or model_setting("OPENAI_BASE_URL", values, "https://api.openai.com/v1")
    model_name = model or model_setting("LLM_MODEL", values) or model_setting("OPENAI_MODEL", values)
    if is_placeholder(api_key):
        raise ValueError(f"未配置 LLM_API_KEY 或 OPENAI_API_KEY，请在 {path} 中设置")
    if not model_name:
        raise ValueError(f"未配置 LLM_MODEL 或 OPENAI_MODEL，请在 {path} 中设置")
    assert base_url is not None
    client = OpenAI(api_key=api_key, base_url=base_url, timeout=60.0)

    def requester(selected_model: str, prompt: str, options: dict[str, Any]) -> dict[str, Any]:
        """将 LLM 请求转发到配置的 OpenAI 兼容服务。"""
        return _post_chat_completion(client, selected_model, prompt, dict(options))

    return LLM(model_name, requester)


def build_evaluator_llm(*, env_file: str | Path | None = None, model: str | None = None) -> LLM:
    """从独立模型环境读取评判模型配置，不自动复用回答模型配置。"""
    path = model_env_path(env_file)
    values = load_model_values(path)
    api_key = model_setting("EVALUATOR_LLM_API_KEY", values)
    base_url = model_setting("EVALUATOR_LLM_BASE_URL", values)
    model_name = model or model_setting("EVALUATOR_LLM_MODEL", values)
    if is_placeholder(api_key) or not model_name:
        raise ValueError(f"未完整配置 EVALUATOR_LLM_API_KEY、EVALUATOR_LLM_BASE_URL、EVALUATOR_LLM_MODEL，请在 {path} 中设置")
    if not base_url:
        base_url = "https://api.openai.com/v1"
    client = OpenAI(api_key=api_key, base_url=base_url, timeout=60.0)

    def requester(selected_model: str, prompt: str, options: dict[str, Any]) -> dict[str, Any]:
        """将评判请求转发到独立的 OpenAI 兼容服务。"""
        return _post_chat_completion(client, selected_model, prompt, dict(options))

    return LLM(model_name, requester)


async def build_llm_async(*, env_file: str | Path | None = None, model: str | None = None) -> LLM:
    """提供异步构建入口，保持与异步 Agent 初始化流程一致。"""
    return await asyncio.to_thread(build_llm, env_file=env_file, model=model)
