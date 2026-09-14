"""向量检索适配器接口和 Chroma 实现。

该模块只封装 Chroma 客户端调用，不参与问题分析或 Agent 决策。检索服务通过
协议注入适配器，因此可以在测试中使用内存假实现，也可以在生产环境使用 Chroma。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Callable, Mapping, Protocol


class VectorSearchAdapter(Protocol):
    """向量数据库适配器，只返回候选 ID、相似度和最小元数据。"""

    async def search(
        self,
        collection: str,
        query_text: str,
        *,
        where: Mapping[str, object] | None = None,
        limit: int = 20,
    ) -> list[dict[str, object]]:
        """根据查询文本检索向量候选。"""

    async def upsert(
        self,
        collection: str,
        ids: list[str],
        documents: list[str],
        metadatas: list[Mapping[str, object]],
    ) -> None:
        """写入或更新向量文档。"""

    async def delete(self, collection: str, ids: list[str]) -> None:
        """删除指定向量。"""


@dataclass(frozen=True)
class ChromaVectorSearchAdapter:
    """基于已创建 Chroma 客户端的异步适配器。

    ``embedding_function`` 由调用方注入，可以是 Chroma 支持的 EmbeddingFunction，
    也可以是兼容 ``__call__`` 的对象。适配器不固定模型，便于切换中文模型。
    """

    client: Any
    embedding_function: Callable[[list[str]], list[list[float]]] | Any | None = None

    def _collection(self, name: str) -> Any:
        """获取集合并在集合不存在时让 Chroma 返回明确错误。"""
        return self.client.get_collection(name=name, embedding_function=self.embedding_function)

    @staticmethod
    def normalize_metadata(metadata: Mapping[str, object]) -> dict[str, object]:
        """将 PostgreSQL 日期时间等类型转换为 Chroma 支持的 metadata 类型。"""
        normalized: dict[str, object] = {}
        for key, value in metadata.items():
            if isinstance(value, (datetime, date)):
                normalized[key] = value.isoformat()
            elif isinstance(value, (str, int, float, bool)):
                normalized[key] = value
            elif value is not None:
                normalized[key] = str(value)
        return normalized

    @staticmethod
    def _where(where: Mapping[str, object] | None) -> dict[str, object] | None:
        """将通用过滤条件转换为 Chroma 的 `$in` 过滤格式。"""
        if not where:
            return None
        clauses: list[dict[str, object]] = []
        for key, value in where.items():
            if isinstance(value, (list, tuple, set)):
                clauses.append({key: {"$in": list(value)}})
            else:
                clauses.append({key: {"$eq": value}})
        return clauses[0] if len(clauses) == 1 else {"$and": clauses}

    async def search(
        self,
        collection: str,
        query_text: str,
        *,
        where: Mapping[str, object] | None = None,
        limit: int = 20,
    ) -> list[dict[str, object]]:
        """调用 Chroma 查询文本并返回标准化候选结果。"""
        safe_limit = max(1, min(limit, 100))

        def run() -> list[dict[str, object]]:
            target = self._collection(collection)
            result = target.query(
                query_texts=[query_text],
                n_results=safe_limit,
                where=self._where(where),
                include=["metadatas", "distances"],
            )
            ids = (result.get("ids") or [[]])[0]
            distances = (result.get("distances") or [[]])[0]
            metadatas = (result.get("metadatas") or [[]])[0]
            candidates: list[dict[str, object]] = []
            for index, item_id in enumerate(ids):
                distance = float(distances[index]) if index < len(distances) else 1.0
                candidates.append({
                    "id": str(item_id),
                    "semantic_score": max(0.0, min(1.0, 1.0 - distance)),
                    "metadata": metadatas[index] if index < len(metadatas) else {},
                })
            return candidates

        return await asyncio.to_thread(run)

    async def upsert(
        self,
        collection: str,
        ids: list[str],
        documents: list[str],
        metadatas: list[Mapping[str, object]],
    ) -> None:
        """将长文本及其元数据写入 Chroma。"""
        if not ids:
            return

        def run() -> None:
            self._collection(collection).upsert(
                ids=ids,
                documents=documents,
                metadatas=[self.normalize_metadata(item) for item in metadatas],
            )

        await asyncio.to_thread(run)

    async def delete(self, collection: str, ids: list[str]) -> None:
        """从 Chroma 删除已失效的长文本向量。"""
        if ids:
            await asyncio.to_thread(lambda: self._collection(collection).delete(ids=ids))
