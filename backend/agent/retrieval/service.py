"""供上层上下文组装流程显式调用的画像和记忆检索函数。

本模块不绑定具体 PostgreSQL 驱动。调用方通过 ``connection_factory`` 注入
psycopg/psycopg2 连接工厂，Agent 层只依赖本模块定义的异步检索接口。

本模块不是 Agent Tool：不会注册工具、监听用户问题或主动触发检索。
只有业务代码在组装上下文时显式调用 ``build_context`` 或具体检索函数，
才会访问数据库并返回结果。
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence


ConnectionFactory = Callable[[], Any]


@dataclass(frozen=True)
class QuestionQuery:
    """问题分析结果，用于决定动态记忆的检索范围。"""

    original: str
    rewritten: str
    topics: tuple[str, ...]
    intent: str
    needs: tuple[str, ...]


class PostgresRetrievalRepository:
    """基于 PostgreSQL 表结构的检索仓储。

    连接工厂由传统后端注入；每次查询独立获取并关闭连接，避免调用方
    持有连接状态。查询结果统一转换为字典，方便直接组装上下文或序列化。
    """

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._connection_factory = connection_factory

    def _query(self, sql: str, params: Sequence[Any]) -> list[dict[str, Any]]:
        """同步执行查询并把游标行转换为字典。"""
        connection = self._connection_factory()
        try:
            cursor = connection.cursor()
            try:
                cursor.execute(sql, params)
                columns = [item[0] for item in cursor.description]
                rows = cursor.fetchall()
                return [dict(zip(columns, row)) for row in rows]
            finally:
                cursor.close()
        finally:
            connection.close()

    async def get_fixed_profile(self, user_id: str) -> dict[str, Any]:
        """读取当前生效版本的固定画像：身份、性格、风格和行为策略。"""
        rows = await asyncio.to_thread(
            self._query,
            """
            SELECT a.id AS avatar_id, a.user_id, a.display_name AS avatar_name,
                   a.summary AS avatar_summary, a.status AS avatar_status,
                   v.id AS version_id, v.version_no,
                   i.display_name, i.summary, i.occupation, i.location, i.age,
                   p.model_name AS personality_model, p.scores AS personality_scores,
                   p.style_tags AS personality_style_tags, p.confidence AS personality_confidence,
                   s.tone AS style_tone, s.structure_rules AS style_structure_rules,
                   s.verbosity, s.technical_density, s.sentence_style,
                   s.uncertainty_style, s.preferred_registers, s.avoid_rules,
                   pol.can_use_unconfirmed_memory, pol.can_present_unconfirmed_as_fact,
                   pol.can_invent_user_experience, pol.can_invent_user_opinion,
                   pol.must_show_uncertainty, pol.must_keep_citations,
                   pol.sensitive_attributes_policy, pol.external_action_requires_confirmation,
                   pol.custom_rules
            FROM public.user_avatars AS a
            JOIN public.avatar_versions AS v
              ON v.id = a.current_version_id AND v.status = 'active'
            LEFT JOIN public.avatar_identity AS i ON i.avatar_version_id = v.id
            LEFT JOIN public.avatar_personality AS p ON p.avatar_version_id = v.id
            LEFT JOIN public.avatar_styles AS s ON s.avatar_version_id = v.id
            LEFT JOIN public.avatar_policies AS pol ON pol.avatar_id = a.id
            WHERE a.user_id = %s AND a.status <> 'archived'
            LIMIT 1
            """,
            (user_id,),
        )
        return rows[0] if rows else {}

    async def search_memories(
        self,
        avatar_id: str,
        query: QuestionQuery,
        *,
        top_k: int = 8,
    ) -> dict[str, list[dict[str, Any]]]:
        """按类型检索观点、行为、专长和兴趣，并过滤不可用记忆。"""
        safe_top_k = max(1, min(top_k, 50))
        topics = list(query.topics) or [query.rewritten]
        rows = await asyncio.to_thread(
            self._query,
            """
            SELECT m.id, m.memory_type, m.topic, m.content, m.structured_data,
                   m.level, m.score, m.confidence, m.status, m.privacy,
                   m.valid_from, m.valid_until, m.evidence_count,
                   COALESCE(jsonb_agg(DISTINCT jsonb_build_object(
                       'source_document_id', e.source_document_id,
                       'quote', e.quote,
                       'evidence_type', e.evidence_type,
                       'relevance_score', e.relevance_score
                   )) FILTER (WHERE e.id IS NOT NULL), '[]'::jsonb) AS evidence
            FROM public.avatar_memories AS m
            LEFT JOIN public.memory_evidence AS e ON e.memory_id = m.id
            WHERE m.avatar_id = %s
              AND m.status IN ('confirmed', 'unconfirmed')
              AND m.privacy IN ('public', 'private')
              AND (m.valid_until IS NULL OR m.valid_until >= now())
              AND (
                    m.topic = ANY(%s)
                    OR m.content ILIKE ANY(%s)
                    OR m.memory_type = ANY(%s)
                  )
            GROUP BY m.id
            ORDER BY
              CASE WHEN m.status = 'confirmed' THEN 0 ELSE 1 END,
              COALESCE(m.score, 0) DESC,
              COALESCE(m.confidence, 0) DESC,
              COALESCE(m.valid_from, m.created_at) DESC
            LIMIT %s
            """,
            (
                avatar_id,
                topics,
                [f"%{item}%" for item in topics],
                list(query.needs),
                safe_top_k,
            ),
        )
        grouped = {"opinions": [], "behavior_memories": [], "expertise": [], "interests": []}
        type_mapping = {"opinion": "opinions", "behavior": "behavior_memories", "expertise": "expertise", "interest": "interests"}
        for row in rows:
            bucket = type_mapping.get(row["memory_type"])
            if bucket:
                grouped[bucket].append(row)
        return grouped

    async def search_source_documents(
        self,
        avatar_id: str,
        query: QuestionQuery,
        *,
        top_k: int = 8,
    ) -> list[dict[str, Any]]:
        """使用 PostgreSQL 全文检索和关键词匹配召回原始知乎内容。"""
        safe_top_k = max(1, min(top_k, 50))
        keywords = [item for item in query.topics if item.strip()]
        rows = await asyncio.to_thread(
            self._query,
            """
            SELECT d.id, d.platform, d.external_id, d.document_type, d.title,
                   d.content, d.source_url, d.published_at, d.imported_at,
                   ts_headline('simple', d.content, plainto_tsquery('simple', %s)) AS quote
            FROM public.source_documents AS d
            WHERE d.avatar_id = %s
              AND (to_tsvector('simple', coalesce(d.title, '') || ' ' || d.content)
                   @@ plainto_tsquery('simple', %s)
                   OR d.title ILIKE ANY(%s)
                   OR d.content ILIKE ANY(%s))
            ORDER BY d.published_at DESC NULLS LAST, d.imported_at DESC
            LIMIT %s
            """,
            (
                query.rewritten,
                avatar_id,
                query.rewritten,
                [f"%{item}%" for item in keywords],
                [f"%{item}%" for item in keywords],
                safe_top_k,
            ),
        )
        return rows

    async def search_chat_history(
        self,
        avatar_id: str,
        question: str,
        *,
        top_k: int = 12,
    ) -> list[dict[str, Any]]:
        """检索该数字分身参与过的历史消息，返回发送者和会话信息。"""
        safe_top_k = max(1, min(top_k, 100))
        return await asyncio.to_thread(
            self._query,
            """
            SELECT m.id AS message_id, m.conversation_id, m.sequence_no,
                   m.message_type, m.content, m.content_format,
                   m.reply_to_message_id, m.sent_at, p.avatar_id,
                   p.display_name, c.title AS conversation_title
            FROM public.chat_messages AS m
            JOIN public.chat_participants AS p ON p.id = m.participant_id
            JOIN public.chat_conversations AS c ON c.id = m.conversation_id
            WHERE m.conversation_id IN (
                SELECT conversation_id
                FROM public.chat_participants
                WHERE avatar_id = %s
            )
              AND m.deleted_at IS NULL
              AND (m.content ILIKE %s OR to_tsvector('simple', m.content)
                   @@ plainto_tsquery('simple', %s))
            ORDER BY m.sent_at DESC, m.sequence_no DESC
            LIMIT %s
            """,
            (avatar_id, f"%{question}%", question, safe_top_k),
        )


def analyze_question(question: str) -> QuestionQuery:
    """使用轻量规则分析问题，生成主题、意图和需要检索的记忆类型。"""
    normalized = " ".join(question.strip().split())
    if not normalized:
        return QuestionQuery("", "", (), "unknown", ("fact",))
    # 中文没有可靠空格分词，先保留完整问题，再提取常见领域词作为主题。
    candidates = re.findall(r"[\u4e00-\u9fff]{2,12}|[A-Za-z][A-Za-z0-9+#.-]{1,30}", normalized)
    topics = tuple(dict.fromkeys(candidates[:12]))
    opinion_words = ("怎么看", "是否", "会不会", "观点", "认为", "看法", "取代", "应该")
    behavior_words = ("遇到", "如何处理", "反应", "情境", "习惯")
    if any(word in normalized for word in opinion_words):
        intent, needs = "opinion_query", ("opinion", "expertise", "source_content")
    elif any(word in normalized for word in behavior_words):
        intent, needs = "behavior_query", ("behavior", "source_content")
    else:
        intent, needs = "general_query", ("expertise", "interest", "source_content")
    return QuestionQuery(normalized, normalized, topics, intent, needs)


async def build_context(
    user_id: str,
    question: str,
    repository: PostgresRetrievalRepository,
    *,
    memory_top_k: int = 8,
    document_top_k: int = 8,
    chat_top_k: int = 12,
) -> dict[str, Any]:
    """并行读取固定画像和动态内容，返回结构化 Agent 上下文。"""
    query = analyze_question(question)
    profile = await repository.get_fixed_profile(user_id)
    if not profile:
        return {
            "query": query.__dict__,
            "profile": {},
            "retrieved_memories": {"opinions": [], "behavior_memories": [], "expertise": [], "interests": []},
            "source_documents": [],
            "chat_history": [],
            "notice": "未找到用户的当前生效数字分身画像。",
        }
    memories, documents, chat_history = await asyncio.gather(
        repository.search_memories(profile["avatar_id"], query, top_k=memory_top_k),
        repository.search_source_documents(profile["avatar_id"], query, top_k=document_top_k),
        repository.search_chat_history(profile["avatar_id"], question, top_k=chat_top_k),
    )
    has_dynamic_result = any(memories.values()) or bool(documents) or bool(chat_history)
    result: dict[str, Any] = {
        "query": query.__dict__,
        "profile": profile,
        "retrieved_memories": memories,
        "source_documents": documents,
        "chat_history": chat_history,
    }
    if not has_dynamic_result:
        result["notice"] = "本轮没有检索到与该问题直接相关的用户记忆，只能进行有限推断，不得虚构用户经历或明确立场。"
    return result
