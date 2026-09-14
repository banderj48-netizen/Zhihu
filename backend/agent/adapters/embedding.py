"""Embedding 模型适配器。

本模块使用官方 OpenAI Python SDK 调用阿里云百炼的 OpenAI 兼容 Embeddings
接口，向 Chroma 暴露其要求的同步 EmbeddingFunction 方法。业务代码只依赖
适配器协议，不直接处理 API 请求和向量格式。
"""

from __future__ import annotations

from typing import Any, Sequence

from openai import OpenAI


class DashScopeEmbeddingFunction:
    """使用阿里云百炼兼容接口生成文本向量的 Chroma EmbeddingFunction。"""

    def __init__(self, *, api_key: str, base_url: str, model: str, batch_size: int = 10) -> None:
        """创建 Embedding 客户端并校验模型配置。"""
        if not api_key.strip():
            raise ValueError("EMBEDDING_API_KEY 不能为空")
        if not base_url.strip():
            raise ValueError("EMBEDDING_BASE_URL 不能为空")
        if not model.strip():
            raise ValueError("EMBEDDING_MODEL 不能为空")
        self.model = model.strip()
        self.base_url = base_url.rstrip("/")
        self.batch_size = max(1, min(int(batch_size), 32))
        # 使用官方 SDK；base_url 由配置注入，不在代码中硬编码密钥。
        self._client = OpenAI(api_key=api_key, base_url=self.base_url, timeout=60.0)

    def name(self) -> str:
        """返回 Chroma 用于标识 EmbeddingFunction 的稳定名称。"""
        return self.model

    def __call__(self, input: Sequence[str]) -> list[list[float]]:
        """兼容 Chroma 的默认调用方式，将文档列表转换为向量列表。"""
        return self.embed_documents(list(input))

    def embed_documents(self, input: Sequence[str]) -> list[list[float]]:
        """批量生成文档向量；按批次请求避免单次输入超出服务限制。"""
        texts = [str(item) for item in input]
        if not texts:
            return []
        vectors: list[list[float]] = []
        for offset in range(0, len(texts), self.batch_size):
            vectors.extend(self._request(texts[offset : offset + self.batch_size]))
        return vectors

    def embed_query(self, input: Sequence[str] | str) -> list[list[float]]:
        """生成查询向量批次，遵循 Chroma 1.x 的 Embeddings 返回协议。"""
        texts = [input] if isinstance(input, str) else [str(item) for item in input]
        return self._request(texts)

    def _request(self, texts: list[str]) -> list[list[float]]:
        """调用 Embeddings API 并按返回的 index 恢复输入顺序。"""
        try:
            response = self._client.embeddings.create(model=self.model, input=texts)
        except Exception as exc:
            # 统一异常信息，保留供应商原始错误，便于复现和定位配置问题。
            raise RuntimeError(f"Embedding 请求失败：{exc}") from exc
        items = sorted(response.data or [], key=lambda item: int(getattr(item, "index", 0)))
        vectors: list[list[float]] = []
        for item in items:
            vector = getattr(item, "embedding", None)
            if not isinstance(vector, list) or not vector:
                raise RuntimeError("Embedding 返回结果缺少有效 embedding")
            vectors.append([float(value) for value in vector])
        if len(vectors) != len(texts):
            raise RuntimeError(f"Embedding 返回数量异常：请求 {len(texts)} 条，返回 {len(vectors)} 条")
        return vectors

