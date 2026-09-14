"""Chroma 客户端和向量集合工厂。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import chromadb
from dotenv import dotenv_values

from agent.adapters.embedding import DashScopeEmbeddingFunction
from agent.adapters.vector_search import ChromaVectorSearchAdapter
from agent.runtime.model_config import load_model_values, model_env_path, model_setting


BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _setting(name: str, values: dict[str, Any], default: str | None = None) -> str | None:
    """按进程环境变量、指定 env 文件、默认值顺序读取配置。"""
    value = os.getenv(name)
    if value is None:
        value = values.get(name)
    if value is None or not str(value).strip():
        return default
    return str(value).strip()


def _values(env_file: str | Path | None = None) -> dict[str, Any]:
    """读取当前后端环境，并让选定环境文件覆盖基础 ``.env``。

    本地启动脚本默认使用 ``.env.local``，而数据库和模型基础配置通常在
    ``.env``。合并读取可以避免启动方式变化导致 Chroma 配置丢失。
    """
    selected = Path(env_file or os.getenv("TWINLOOP_ENV_FILE") or (BACKEND_ROOT / ".env"))
    merged: dict[str, Any] = {}
    base = BACKEND_ROOT / ".env"
    if base.exists():
        merged.update(dict(dotenv_values(base)))
    if selected.exists() and selected.resolve() != base.resolve():
        merged.update(dict(dotenv_values(selected)))
    return merged


def embedding_config(env_file: str | Path | None = None) -> dict[str, str]:
    """返回阿里云 Embedding 配置；API Key 缺失时抛出可读错误。"""
    path = model_env_path(env_file)
    values = load_model_values(path)
    api_key = model_setting("EMBEDDING_API_KEY", values)
    base_url = model_setting("EMBEDDING_BASE_URL", values, "https://dashscope.aliyuncs.com/compatible-mode/v1")
    model = model_setting("EMBEDDING_MODEL", values, "qwen3.7-text-embedding-flash")
    if not api_key:
        raise ValueError(f"未配置 EMBEDDING_API_KEY，请在 {path} 中设置")
    assert base_url and model
    batch_size = model_setting("EMBEDDING_BATCH_SIZE", values, "10") or "10"
    return {"api_key": api_key, "base_url": base_url, "model": model, "batch_size": batch_size}


def embedding_model_name(env_file: str | Path | None = None) -> str:
    """返回当前生效的 Embedding 模型名，不读取或返回 API Key。"""
    values = load_model_values(model_env_path(env_file))
    return model_setting("EMBEDDING_MODEL", values, "qwen3.7-text-embedding-flash") or "qwen3.7-text-embedding-flash"


def create_chroma_vector_store(env_file: str | Path | None = None) -> ChromaVectorSearchAdapter:
    """创建持久化 Chroma 适配器并确保三个业务集合存在。"""
    values = _values(env_file)
    mode = (_setting("CHROMA_MODE", values, "persistent") or "persistent").lower()
    if mode == "http":
        host = _setting("CHROMA_HOST", values, "127.0.0.1") or "127.0.0.1"
        port = int(_setting("CHROMA_PORT", values, "8001") or "8001")
        client = chromadb.HttpClient(host=host, port=port, ssl=(_setting("CHROMA_SSL", values, "false") or "false").lower() == "true")
    else:
        directory = Path(_setting("CHROMA_PERSIST_DIRECTORY", values, str(BACKEND_ROOT / "data" / "chroma")) or (BACKEND_ROOT / "data" / "chroma"))
        directory.mkdir(parents=True, exist_ok=True)
        client = chromadb.PersistentClient(path=str(directory))
    # Chroma 的目录/服务地址属于应用环境；Embedding 凭据始终从独立模型环境读取。
    config = embedding_config()
    embedding = DashScopeEmbeddingFunction(api_key=config["api_key"], base_url=config["base_url"], model=config["model"], batch_size=int(config["batch_size"]))
    collections = {
        "avatar_memories": _setting("CHROMA_MEMORY_COLLECTION", values, "avatar_memories") or "avatar_memories",
        "source_documents": _setting("CHROMA_SOURCE_COLLECTION", values, "source_documents") or "source_documents",
        "chat_messages": _setting("CHROMA_CHAT_COLLECTION", values, "chat_messages") or "chat_messages",
    }
    # 适配器使用 get_collection；这里先创建集合，避免首次 upsert 抛 NotFoundError。
    for name in collections.values():
        client.get_or_create_collection(name=name, embedding_function=embedding)
    return ChromaVectorSearchAdapter(client=client, embedding_function=embedding)

