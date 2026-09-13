"""供上下文组装流程显式调用的 PostgreSQL + Chroma 分层检索函数。"""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Sequence

from agent.adapters.vector_search import VectorSearchAdapter

ConnectionFactory = Callable[[], Any]
MEMORY_TYPES = ("experience", "fact", "opinion", "behavior", "expertise", "interest")


@dataclass(frozen=True)
class QueryPlan:
    """问题分析后的主题、意图和检索类型。"""

    original_question: str
    rewritten_question: str
    topics: tuple[str, ...]
    intent: str
    needs: tuple[str, ...]
    keywords: tuple[str, ...]


def analyze_question(question: str) -> QueryPlan:
    """使用规则提取主题和意图；不会调用模型或数据库。"""
    text = " ".join(question.strip().split())
    words = tuple(dict.fromkeys(re.findall(r"[\u4e00-\u9fff]{2,12}|[A-Za-z][A-Za-z0-9+#.-]{1,30}", text)[:16]))
    if any(x in text for x in ("怎么看", "是否", "会不会", "观点", "认为", "看法")):
        intent, needs = "opinion_query", ("opinion", "expertise", "source_document", "chat_history")
    elif any(x in text for x in ("遇到", "如何处理", "反应", "情境", "习惯")):
        intent, needs = "behavior_query", ("behavior", "experience", "source_document", "chat_history")
    else:
        intent, needs = "general_query", ("experience", "opinion", "expertise", "interest", "source_document", "chat_history")
    return QueryPlan(text, text, words, intent, needs, words)


class PostgresRetrievalRepository:
    """读取 PostgreSQL 完整事实数据的仓储；不负责向量检索。"""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._factory = connection_factory

    def _query(self, sql: str, params: Sequence[Any]) -> list[dict[str, Any]]:
        """执行只读 SQL 并将结果转换为字典。"""
        conn = self._factory()
        try:
            cur = conn.cursor()
            try:
                cur.execute(sql, params)
                names = [item[0] for item in cur.description]
                return [dict(zip(names, row)) for row in cur.fetchall()]
            finally:
                cur.close()
        finally:
            conn.close()

    async def _select(self, sql: str, params: Sequence[Any]) -> list[dict[str, Any]]:
        """在线程中异步执行 PostgreSQL 查询。"""
        return await asyncio.to_thread(self._query, sql, params)

    async def get_fixed_profile(self, user_id: str) -> dict[str, Any]:
        """直接查询当前生效的身份、性格、风格和策略，不经过 Chroma。"""
        rows = await self._select("""
            SELECT a.id AS avatar_id, a.user_id, a.display_name AS avatar_name, a.summary AS avatar_summary,
                   v.id AS version_id, v.version_no, i.display_name, i.summary, i.occupation, i.location, i.age,
                   p.model_name AS personality_model, p.scores AS personality_scores, p.style_tags AS personality_style_tags,
                   p.confidence AS personality_confidence, p.status AS personality_status,
                   s.tone AS style_tone, s.structure_rules AS style_structure_rules, s.verbosity, s.technical_density,
                   s.sentence_style, s.uncertainty_style, s.preferred_registers, s.avoid_rules,
                   pol.can_use_unconfirmed_memory, pol.can_present_unconfirmed_as_fact, pol.can_invent_user_experience,
                   pol.can_invent_user_opinion, pol.must_show_uncertainty, pol.must_keep_citations,
                   pol.sensitive_attributes_policy, pol.external_action_requires_confirmation, pol.custom_rules
            FROM public.user_avatars a
            JOIN public.avatar_versions v ON v.id = a.current_version_id AND v.status = 'active'
            LEFT JOIN public.avatar_identity i ON i.avatar_version_id = v.id
            LEFT JOIN public.avatar_personality p ON p.avatar_version_id = v.id
            LEFT JOIN public.avatar_styles s ON s.avatar_version_id = v.id
            LEFT JOIN public.avatar_policies pol ON pol.avatar_id = a.id
            WHERE a.user_id = %s AND a.status <> 'archived' LIMIT 1
        """, (user_id,))
        return rows[0] if rows else {}

    async def search_memory_keywords(self, avatar_id: str, query: QueryPlan, *, limit: int) -> list[dict[str, Any]]:
        """用 PostgreSQL 主题和正文关键词召回长记忆候选。"""
        terms = [f"%{x}%" for x in query.keywords] or ["%"]
        return await self._select("""
            SELECT m.id AS memory_id, m.memory_type, m.topic, m.content, m.structured_data, m.level, m.score,
                   m.confidence, m.status, m.privacy, m.valid_from, m.valid_until, m.evidence_count, 1.0::float AS keyword_score
            FROM public.avatar_memories m
            WHERE m.avatar_id = %s AND m.memory_type = ANY(%s) AND m.status IN ('confirmed','unconfirmed')
              AND m.privacy IN ('public','private') AND (m.valid_until IS NULL OR m.valid_until >= now())
              AND (m.topic ILIKE ANY(%s) OR m.content ILIKE ANY(%s))
            ORDER BY CASE WHEN m.status = 'confirmed' THEN 0 ELSE 1 END, COALESCE(m.confidence,0) DESC
            LIMIT %s
        """, (avatar_id, list(MEMORY_TYPES), terms, terms, max(1, min(limit, 100))))

    async def fetch_memories_by_ids(self, avatar_id: str, ids: Sequence[str]) -> list[dict[str, Any]]:
        """按 Chroma 返回的记忆 ID 回表并再次执行权限过滤。"""
        if not ids:
            return []
        return await self._select("""
            SELECT m.id AS memory_id, m.memory_type, m.topic, m.content, m.structured_data, m.level, m.score,
                   m.confidence, m.status, m.privacy, m.valid_from, m.valid_until, m.evidence_count
            FROM public.avatar_memories m WHERE m.avatar_id = %s AND m.id = ANY(%s)
              AND m.status IN ('confirmed','unconfirmed') AND m.privacy IN ('public','private')
              AND (m.valid_until IS NULL OR m.valid_until >= now())
        """, (avatar_id, list(ids)))

    async def search_source_keywords(self, avatar_id: str, query: QueryPlan, *, limit: int) -> list[dict[str, Any]]:
        """用 PostgreSQL 全文和关键词检索原始资料。"""
        terms = [f"%{x}%" for x in query.keywords] or ["%"]
        return await self._select("""
            SELECT d.id AS document_id, d.platform, d.external_id, d.document_type, d.title, d.content,
                   d.source_url, d.published_at, d.imported_at,
                   ts_headline('simple', d.content, plainto_tsquery('simple', %s)) AS quote, 1.0::float AS keyword_score
            FROM public.source_documents d
            WHERE d.avatar_id = %s AND (to_tsvector('simple', coalesce(d.title,'') || ' ' || d.content)
                @@ plainto_tsquery('simple', %s) OR d.title ILIKE ANY(%s) OR d.content ILIKE ANY(%s))
            ORDER BY d.published_at DESC NULLS LAST, d.imported_at DESC LIMIT %s
        """, (query.rewritten_question, avatar_id, query.rewritten_question, terms, terms, max(1, min(limit, 100))))

    async def fetch_documents_by_ids(self, avatar_id: str, ids: Sequence[str]) -> list[dict[str, Any]]:
        """按 Chroma 返回的文档 ID 回表获取完整内容。"""
        if not ids:
            return []
        return await self._select("""SELECT id AS document_id, platform, external_id, document_type, title, content,
                   source_url, published_at, imported_at FROM public.source_documents
                   WHERE avatar_id = %s AND id = ANY(%s)""", (avatar_id, list(ids)))

    async def search_chat_keywords(self, avatar_id: str, query: QueryPlan, *, conversation_id: str | None, limit: int) -> list[dict[str, Any]]:
        """用 PostgreSQL 全文和关键词检索未删除聊天消息。"""
        return await self._select("""
            SELECT m.id AS message_id, m.conversation_id, m.participant_id, m.sequence_no, m.message_type,
                   m.content, m.content_format, m.reply_to_message_id, m.sent_at, p.avatar_id, p.display_name,
                   c.title AS conversation_title, 1.0::float AS keyword_score
            FROM public.chat_messages m JOIN public.chat_participants p ON p.id=m.participant_id
            JOIN public.chat_conversations c ON c.id=m.conversation_id
            WHERE p.avatar_id=%s AND m.deleted_at IS NULL AND c.status <> 'deleted'
              AND (%s IS NULL OR m.conversation_id=%s)
              AND (m.content ILIKE %s OR to_tsvector('simple',m.content) @@ plainto_tsquery('simple',%s))
            ORDER BY m.sent_at DESC, m.sequence_no DESC LIMIT %s
        """, (avatar_id, conversation_id, conversation_id, f"%{query.rewritten_question}%", query.rewritten_question, max(1, min(limit, 100))))

    async def fetch_chat_by_ids(self, avatar_id: str, ids: Sequence[str]) -> list[dict[str, Any]]:
        """按 Chroma 消息 ID 回表确认消息仍然有效。"""
        if not ids:
            return []
        return await self._select("""SELECT m.id AS message_id,m.conversation_id,m.participant_id,m.sequence_no,
                   m.message_type,m.content,m.content_format,m.reply_to_message_id,m.sent_at,p.avatar_id,p.display_name,
                   c.title AS conversation_title FROM public.chat_messages m
                   JOIN public.chat_participants p ON p.id=m.participant_id JOIN public.chat_conversations c ON c.id=m.conversation_id
                   WHERE p.avatar_id=%s AND m.id=ANY(%s) AND m.deleted_at IS NULL AND c.status <> 'deleted'""", (avatar_id, list(ids)))

    async def fetch_chat_window(self, conversation_id: str, sequence_no: int, window: int = 3) -> list[dict[str, Any]]:
        """读取命中消息前后的同会话窗口，并按序号排序。"""
        return await self._select("""SELECT m.id AS message_id,m.conversation_id,m.sequence_no,m.content,m.message_type,
                   m.sent_at,p.avatar_id,p.display_name FROM public.chat_messages m
                   JOIN public.chat_participants p ON p.id=m.participant_id
                   WHERE m.conversation_id=%s AND m.deleted_at IS NULL AND m.sequence_no BETWEEN %s AND %s
                   ORDER BY m.sequence_no ASC""", (conversation_id, max(0, sequence_no-window), sequence_no+window))


def _memory_score(row: Mapping[str, Any], semantic: float, intent: str) -> float:
    """按混合检索权重计算记忆分数。"""
    expected = {"opinion_query": "opinion", "behavior_query": "behavior"}.get(intent)
    intent_score = 1.0 if expected and row.get("memory_type") == expected else 0.5
    confirm = 1.0 if row.get("status") == "confirmed" else 0.4
    return 0.35 * semantic + 0.25 * float(row.get("keyword_score") or 0) + 0.15 * intent_score + 0.10 * float(row.get("confidence") or 0) + 0.10 * confirm + 0.05


async def search_long_memories(repository: PostgresRetrievalRepository, vector: VectorSearchAdapter, avatar_id: str, query: QueryPlan, *, top_k: int = 8) -> dict[str, list[dict[str, Any]]]:
    """混合检索经历、观点、行为、专长和兴趣，按类型返回。"""
    keyword_rows, vector_rows = await asyncio.gather(repository.search_memory_keywords(avatar_id, query, limit=top_k*3), vector.search("avatar_memories", query.rewritten_question, where={"avatar_id": avatar_id, "status": ["confirmed", "unconfirmed"], "privacy": ["public", "private"]}, limit=top_k*3))
    merged = {str(r["memory_id"]): {**r, "semantic_score": 0.0} for r in keyword_rows}
    db_rows = await repository.fetch_memories_by_ids(avatar_id, [str(x["id"]) for x in vector_rows])
    for row in db_rows:
        merged.setdefault(str(row["memory_id"]), {**row, "keyword_score": 0.0})
    for item in vector_rows:
        if str(item["id"]) in merged: merged[str(item["id"])]["semantic_score"] = float(item.get("semantic_score") or 0)
    groups = {"experiences": [], "opinions": [], "behavior_memories": [], "expertise": [], "interests": []}
    mapping = {"experience": "experiences", "fact": "experiences", "opinion": "opinions", "behavior": "behavior_memories", "expertise": "expertise", "interest": "interests"}
    for row in merged.values():
        row["relevance_score"] = _memory_score(row, float(row.get("semantic_score") or 0), query.intent)
        if mapping.get(row.get("memory_type")): groups[mapping[row["memory_type"]]].append(row)
    for rows in groups.values(): rows.sort(key=lambda x: x["relevance_score"], reverse=True); del rows[top_k:]
    return groups


async def search_source_documents(repository: PostgresRetrievalRepository, vector: VectorSearchAdapter, avatar_id: str, query: QueryPlan, *, top_k: int = 8) -> list[dict[str, Any]]:
    """混合检索知乎原始资料；Chroma 仅返回候选 ID，正文由 PostgreSQL 提供。"""
    keyword_rows, vector_rows = await asyncio.gather(repository.search_source_keywords(avatar_id, query, limit=top_k * 3), vector.search("source_documents", query.rewritten_question, where={"avatar_id": avatar_id}, limit=top_k * 3))
    merged = {str(r["document_id"]): {**r, "semantic_score": 0.0} for r in keyword_rows}
    vector_ids = [str((x.get("metadata") or {}).get("document_id") or x["id"]) for x in vector_rows]
    db_rows = await repository.fetch_documents_by_ids(avatar_id, vector_ids)
    for row in db_rows: merged.setdefault(str(row["document_id"]), {**row, "keyword_score": 0.0})
    for item in vector_rows:
        if str(item["id"]) in merged: merged[str(item["id"])]["semantic_score"] = float(item.get("semantic_score") or 0)
    for row in merged.values(): row["relevance_score"] = 0.45 * float(row.get("semantic_score") or 0) + 0.30 * float(row.get("keyword_score") or 0) + 0.25
    return sorted(merged.values(), key=lambda x: x["relevance_score"], reverse=True)[:top_k]


async def search_chat_history(repository: PostgresRetrievalRepository, vector: VectorSearchAdapter, avatar_id: str, query: QueryPlan, *, conversation_id: str | None = None, top_k: int = 12, context_window: int = 3) -> list[dict[str, Any]]:
    """混合检索聊天消息并扩展命中消息的前后文窗口。"""
    keyword_rows, vector_rows = await asyncio.gather(repository.search_chat_keywords(avatar_id, query, conversation_id=conversation_id, limit=top_k * 3), vector.search("chat_messages", query.rewritten_question, where={"avatar_id": avatar_id, "deleted": False, **({"conversation_id": conversation_id} if conversation_id else {})}, limit=top_k * 3))
    merged = {str(r["message_id"]): {**r, "semantic_score": 0.0} for r in keyword_rows}
    db_rows = await repository.fetch_chat_by_ids(avatar_id, [str(x["id"]) for x in vector_rows])
    for row in db_rows: merged.setdefault(str(row["message_id"]), {**row, "keyword_score": 0.0})
    for item in vector_rows:
        if str(item["id"]) in merged: merged[str(item["id"])]["semantic_score"] = float(item.get("semantic_score") or 0)
    for row in merged.values(): row["relevance_score"] = 0.35 * float(row.get("semantic_score") or 0) + 0.25 * float(row.get("keyword_score") or 0) + 0.40
    result = []
    for row in sorted(merged.values(), key=lambda x: x["relevance_score"], reverse=True)[:top_k]:
        result.append({"conversation_id": row["conversation_id"], "matched_message_id": row["message_id"], "relevance_score": row["relevance_score"], "messages": await repository.fetch_chat_window(str(row["conversation_id"]), int(row["sequence_no"]), context_window)})
    return result


async def build_context(user_id: str, question: str, repository: PostgresRetrievalRepository, vector_search: VectorSearchAdapter, *, conversation_id: str | None = None, memory_top_k: int = 8, document_top_k: int = 8, chat_top_k: int = 12, context_window: int = 3) -> dict[str, Any]:
    """由调用方显式执行，组装固定画像与 PostgreSQL+Chroma 动态检索结果。"""
    query = analyze_question(question)
    profile = await repository.get_fixed_profile(user_id)
    empty = {"experiences": [], "opinions": [], "behavior_memories": [], "expertise": [], "interests": []}
    if not profile: return {"query": query.__dict__, "profile": {}, "retrieved_memories": empty, "source_documents": [], "chat_history": [], "notice": "未找到用户当前生效的数字分身画像。"}
    avatar_id = str(profile["avatar_id"])
    memories, documents, chats = await asyncio.gather(search_long_memories(repository, vector_search, avatar_id, query, top_k=memory_top_k), search_source_documents(repository, vector_search, avatar_id, query, top_k=document_top_k), search_chat_history(repository, vector_search, avatar_id, query, conversation_id=conversation_id, top_k=chat_top_k, context_window=context_window))
    result: dict[str, Any] = {"query": query.__dict__, "profile": profile, "retrieved_memories": memories, "source_documents": documents, "chat_history": chats, "retrieval_meta": {"memory_count": sum(len(v) for v in memories.values()), "document_count": len(documents), "chat_message_count": len(chats), "generated_at": datetime.now(timezone.utc).isoformat()}}
    if not any(memories.values()) and not documents and not chats: result["notice"] = "本轮没有检索到与该问题直接相关的用户记忆。只能根据固定画像进行有限推断，不得虚构用户经历或明确立场。"
    return result


async def index_memory(memory: Mapping[str, object], vector_store: VectorSearchAdapter, *, collection: str = "avatar_memories", embedding_model: str | None = None, embedding_dimension: int | None = None) -> None:
    """将一条有效长记忆写入 Chroma，并记录模型名称和维度。"""
    memory_id = str(memory["memory_id"] if "memory_id" in memory else memory["id"])
    metadata = {key: value for key, value in memory.items() if key in {"avatar_id", "user_id", "memory_type", "topic", "status", "privacy", "confidence"}}
    metadata["memory_id"] = memory_id
    if embedding_model: metadata["embedding_model"] = embedding_model
    if embedding_dimension: metadata["embedding_dimension"] = embedding_dimension
    await vector_store.upsert(collection, [memory_id], [str(memory.get("content", ""))], [metadata])


async def index_source_document_chunk(document: Mapping[str, object], vector_store: VectorSearchAdapter, *, collection: str = "source_documents", embedding_model: str | None = None, embedding_dimension: int | None = None) -> None:
    """将一段原始资料写入 Chroma，Payload 保存文档和片段标识。"""
    item_id = str(document.get("chunk_id") or document.get("document_id") or document["id"])
    metadata = {key: value for key, value in document.items() if key in {"avatar_id", "user_id", "document_id", "platform", "document_type", "chunk_index"}}
    metadata["document_id"] = str(document.get("document_id") or document.get("id"))
    if embedding_model: metadata["embedding_model"] = embedding_model
    if embedding_dimension: metadata["embedding_dimension"] = embedding_dimension
    await vector_store.upsert(collection, [item_id], [str(document.get("content") or document.get("quote") or "")], [metadata])


async def index_chat_message(message: Mapping[str, object], vector_store: VectorSearchAdapter, *, collection: str = "chat_messages", embedding_model: str | None = None, embedding_dimension: int | None = None) -> None:
    """将一条未删除聊天消息写入 Chroma，并保存会话顺序和模型信息。"""
    item_id = str(message.get("message_id") or message["id"])
    metadata = {key: value for key, value in message.items() if key in {"avatar_id", "user_id", "conversation_id", "participant_id", "sequence_no", "sent_at", "message_type"}}
    metadata.update({"message_id": item_id, "deleted": bool(message.get("deleted", False))})
    if embedding_model: metadata["embedding_model"] = embedding_model
    if embedding_dimension: metadata["embedding_dimension"] = embedding_dimension
    await vector_store.upsert(collection, [item_id], [str(message.get("content", ""))], [metadata])
