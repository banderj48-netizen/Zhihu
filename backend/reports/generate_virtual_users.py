"""根据自然语言要求生成并落库虚拟用户画像、记忆和知乎原始资料。

脚本通过 ``backend/.env.models`` 中的 LLM 配置生成结构化 JSON，随后使用项目
现有的 ``ProfileRepository`` 写入 PostgreSQL，并消费 ``vector_sync_outbox`` 同步
到 Chroma。默认不删除任何已有数据；每个生成用户都带有 ``generated-`` 前缀，
便于后续审计、检索和人工清理。
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from psycopg.types.json import Jsonb

from agent.profile.repository import ProfileRepository
from agent.profile.proposals import ProfileProposal
from agent.runtime.model_builder import build_llm
from agent.runtime.model_config import load_model_values, model_env_path, model_setting
from agent.adapters.chroma_factory import create_chroma_vector_store
from agent.profile.outbox import sync_pending
from db.database import connect, initialize_formal


ALLOWED_MEMORY_TYPES = {"fact", "experience", "opinion", "behavior", "expertise", "interest"}
ALLOWED_LEVELS = {"deep", "middle", "shallow"}
ALLOWED_PRIVACY = {"private", "public", "sensitive"}
DEFAULT_POLICY = {
    "can_use_unconfirmed_memory": True,
    "can_present_unconfirmed_as_fact": False,
    "can_invent_user_experience": False,
    "can_invent_user_opinion": False,
    "must_show_uncertainty": True,
    "must_keep_citations": True,
    "sensitive_attributes_policy": "do_not_infer",
    "external_action_requires_confirmation": True,
}


def _read_request(request: str | None, input_file: str | None) -> str:
    """读取命令行文本或 UTF-8 文件中的虚拟用户生成要求。"""
    if request and request.strip():
        return request.strip()
    if input_file:
        return Path(input_file).read_text(encoding="utf-8").strip()
    if not sys.stdin.isatty():
        return sys.stdin.read().strip()
    raise ValueError("请通过位置参数、--input-file 或标准输入提供生成要求")


def _extract_json(text: str) -> Any:
    """解析模型返回的 JSON，兼容 Markdown fenced code block 和前后解释文本。"""
    raw = text.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}|\[.*\]", raw, flags=re.DOTALL)
        if not match:
            raise ValueError("LLM 未返回可解析的 JSON")
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise ValueError(f"LLM JSON 解析失败：{exc}") from exc


def _as_text(value: Any, default: str = "") -> str:
    """把模型字段转换为去首尾空白的字符串。"""
    return str(value if value is not None else default).strip()


def _as_list(value: Any) -> list[Any]:
    """将模型字段安全转换为列表。"""
    return list(value) if isinstance(value, list) else []


def _normalize_user(raw: Mapping[str, Any], index: int, request_hash: str) -> dict[str, Any]:
    """校验并补齐单个模型生成的虚拟用户结构。"""
    identity = dict(raw.get("identity") or {})
    display_name = _as_text(identity.get("display_name"), f"虚拟用户{index}")[:100]
    summary = _as_text(identity.get("summary"), "由生成脚本创建的虚拟用户")
    personality = dict(raw.get("personality") or {})
    personality.setdefault("model_name", "generated_profile_v1")
    personality.setdefault("scores", {})
    personality.setdefault("style_tags", [])
    personality.setdefault("confidence", 0.75)
    personality.setdefault("inference_source", "llm_generated_simulation")
    personality.setdefault("status", "unconfirmed")
    style = dict(raw.get("style") or {})
    style.setdefault("tone", [])
    style.setdefault("structure_rules", [])
    style.setdefault("verbosity", "medium")
    style.setdefault("technical_density", "medium")
    style.setdefault("sentence_style", "自然、具体、避免空泛结论")
    style.setdefault("uncertainty_style", "证据不足时明确说明不确定")
    style.setdefault("preferred_registers", ["chat", "answer"])
    style.setdefault("avoid_rules", ["不得虚构没有证据的真实经历"])
    policy = {**DEFAULT_POLICY, **dict(raw.get("policy") or {})}
    memory_rules = {"top_k": 8, "use_vector_search": True, "use_keyword_search": True, "prefer_confirmed": True, "prefer_recent_opinions": True, **dict(raw.get("memory_rules") or {})}
    documents: list[dict[str, Any]] = []
    for doc_index, raw_doc in enumerate(_as_list(raw.get("source_documents"))[:20], 1):
        if not isinstance(raw_doc, Mapping):
            continue
        content = _as_text(raw_doc.get("content"))
        if not content:
            continue
        document_type = _as_text(raw_doc.get("document_type"), "answer")[:32]
        suffix = re.sub(r"[^a-zA-Z0-9_-]+", "-", _as_text(raw_doc.get("external_id_suffix"), f"source-{doc_index}"))[:80].strip("-") or f"source-{doc_index}"
        documents.append({
            "external_id_suffix": suffix,
            "document_type": document_type,
            "title": _as_text(raw_doc.get("title"), f"虚拟知乎资料 {doc_index}"),
            "content": content,
            "source_url": _as_text(raw_doc.get("source_url")) or None,
            "metadata": dict(raw_doc.get("metadata") or {}),
            "style_register": _as_text(raw_doc.get("style_register"), "answer"),
        })
    memories: list[dict[str, Any]] = []
    for raw_memory in _as_list(raw.get("memories"))[:50]:
        if not isinstance(raw_memory, Mapping):
            continue
        content = _as_text(raw_memory.get("content"))
        if not content:
            continue
        memory_type = _as_text(raw_memory.get("memory_type"), "fact")
        if memory_type not in ALLOWED_MEMORY_TYPES:
            memory_type = "fact"
        level = _as_text(raw_memory.get("level"), "middle")
        if level not in ALLOWED_LEVELS:
            level = "middle"
        privacy = _as_text(raw_memory.get("privacy"), "private")
        if privacy not in ALLOWED_PRIVACY:
            privacy = "private"
        source_indexes = [int(x) for x in _as_list(raw_memory.get("source_document_indexes")) if isinstance(x, int) and x >= 1]
        memories.append({
            "memory_type": memory_type,
            "topic": _as_text(raw_memory.get("topic"))[:200] or None,
            "content": content,
            "structured_data": dict(raw_memory.get("structured_data") or {}),
            "level": level,
            "score": raw_memory.get("score"),
            "confidence": raw_memory.get("confidence", 0.75),
            "status": "unconfirmed" if _as_text(raw_memory.get("status"), "unconfirmed") not in {"confirmed", "unconfirmed"} else _as_text(raw_memory.get("status"), "unconfirmed"),
            "privacy": privacy,
            "source_document_indexes": source_indexes,
        })
    if not memories:
        memories.append({"memory_type": "fact", "topic": "生成要求", "content": summary, "structured_data": {"source": "llm_generated_simulation"}, "level": "middle", "score": 0.7, "confidence": 0.7, "status": "unconfirmed", "privacy": "private", "source_document_indexes": []})
    return {"identity": {**identity, "display_name": display_name, "summary": summary}, "personality": personality, "style": style, "policy": policy, "memory_rules": memory_rules, "source_documents": documents, "memories": memories, "generation_metadata": {"request_hash": request_hash, "raw_label": _as_text(raw.get("label"), f"user-{index}")}}


def _prompt(request: str, count: int) -> str:
    """构造要求模型严格返回可落库的中文虚拟用户 JSON。"""
    schema = {
        "users": [{
            "label": "短标签",
            "identity": {"display_name": "", "summary": "", "occupation": "", "location": "", "age": None, "privacy_level": "private", "extra": {}},
            "personality": {"model_name": "generated_profile_v1", "scores": {"openness": 0.0, "conscientiousness": 0.0, "extraversion": 0.0, "agreeableness": 0.0, "neuroticism": 0.0}, "style_tags": [], "confidence": 0.75, "status": "unconfirmed"},
            "style": {"tone": [], "structure_rules": [], "verbosity": "medium", "technical_density": "medium", "sentence_style": "", "uncertainty_style": "", "preferred_registers": ["chat", "answer"], "avoid_rules": []},
            "policy": {"can_use_unconfirmed_memory": True, "can_present_unconfirmed_as_fact": False, "can_invent_user_experience": False, "can_invent_user_opinion": False, "must_show_uncertainty": True, "must_keep_citations": True, "sensitive_attributes_policy": "do_not_infer", "external_action_requires_confirmation": True},
            "memory_rules": {"top_k": 8, "use_vector_search": True, "use_keyword_search": True, "prefer_confirmed": True, "prefer_recent_opinions": True},
            "memories": [{"memory_type": "interest|expertise|experience|opinion|behavior|fact", "topic": "", "content": "", "structured_data": {}, "level": "deep|middle|shallow", "score": 0.0, "confidence": 0.0, "status": "unconfirmed", "privacy": "private|public", "source_document_indexes": [1]}],
            "source_documents": [{"external_id_suffix": "answer-1", "document_type": "answer", "title": "", "content": "模拟该用户写过的知乎原始正文，不要声称是真实来源。", "source_url": "", "metadata": {"simulated": True}, "style_register": "answer"}]
        }]
    }
    return json.dumps({"request": request, "count": count, "output_schema": schema, "rules": ["只返回 JSON，不要 Markdown 或解释文字", "所有内容使用中文，贴近用户要求", "资料必须明确是 simulated/generated，不能伪造真实知乎外部 ID", "至少生成 3 条记忆和 2 篇原始资料", "记忆中的 source_document_indexes 从 1 开始"]}, ensure_ascii=False)


async def _generate(request: str, count: int, model: str | None, model_response_file: str | None = None) -> list[dict[str, Any]]:
    """调用注入式 LLM 并解析多个虚拟用户；可用响应文件复现同一批数据。"""
    if model_response_file:
        response_text = Path(model_response_file).read_text(encoding="utf-8")
    else:
        llm = build_llm(model=model)
        response = await llm.generate(_prompt(request, count), system_prompt="你是 TwinLoop 的虚拟用户数据生成器。输出必须符合 JSON schema。生成的是模拟测试数据，不能冒充真实人物或真实知乎资料。", temperature=0.4, max_tokens=12000)
        response_text = response.text
    parsed = _extract_json(response_text)
    raw_users = parsed.get("users") if isinstance(parsed, Mapping) else parsed
    if not isinstance(raw_users, list) or not raw_users:
        raise ValueError("LLM JSON 缺少 users 数组")
    request_hash = hashlib.sha256(request.encode("utf-8")).hexdigest()
    normalized = [_normalize_user(item, index, request_hash) for index, item in enumerate(raw_users[:count], 1) if isinstance(item, Mapping)]
    if len(normalized) != count:
        raise ValueError(f"LLM 只生成了 {len(normalized)} 个用户，期望 {count} 个")
    return normalized


def _write_user(raw: Mapping[str, Any], request: str, index: int) -> dict[str, Any]:
    """把单个虚拟用户写入 PostgreSQL，并建立记忆与原始资料证据关系。"""
    repository = ProfileRepository()
    user_id = str(uuid4())
    label = re.sub(r"[^a-zA-Z0-9_-]+", "-", _as_text(raw["generation_metadata"].get("raw_label"), f"user-{index}"))[:60].strip("-") or f"user-{index}"
    external_id = f"generated-{label}-{user_id[:8]}"
    profile = repository.initialize_avatar(user_id=user_id, identity=raw["identity"], personality=raw["personality"], style=raw["style"], policy=raw["policy"], memory_rules=raw["memory_rules"])
    avatar_id = str(profile["avatar_id"])
    with connect() as db:
        db.execute("UPDATE users SET external_id=%s,updated_at=now() WHERE id=%s", (external_id, user_id))
        db.execute("UPDATE user_avatars SET metadata=metadata || %s,updated_at=now() WHERE id=%s", (Jsonb({"generated": True, "generator": "generate_virtual_users.py", "request_hash": hashlib.sha256(request.encode("utf-8")).hexdigest()}), avatar_id))
    source_ids: list[str] = []
    for doc_index, document in enumerate(raw["source_documents"], 1):
        source_id = repository.write_source(user_id=user_id, avatar_id=avatar_id, platform="zhihu", document_type=document["document_type"], content=document["content"], source_url=document.get("source_url"), external_id=f"{external_id}-{document['external_id_suffix']}", metadata={**document["metadata"], "simulated": True, "generated_by": "generate_virtual_users.py", "display_title": document["title"]})
        source_ids.append(source_id)
        with connect() as db:
            db.execute("INSERT INTO avatar_style_examples(avatar_id,register,text,source_document_id) VALUES(%s,%s,%s,%s)", (avatar_id, document.get("style_register") or "answer", document["content"], source_id))
    version_id = str(profile["version_id"])
    memory_ids: list[str] = []
    for memory in raw["memories"]:
        refs = [source_ids[i - 1] for i in memory["source_document_indexes"] if 1 <= i <= len(source_ids)]
        proposal = ProfileProposal(user_id=user_id, avatar_id=avatar_id, base_version_id=version_id, proposal_type=f"propose_{memory['memory_type']}_memory", payload={"memory_type": memory["memory_type"], "topic": memory["topic"], "content": memory["content"], "level": memory["level"], "structured_data": {**memory["structured_data"], "simulated": True}}, source_refs=refs, confidence=float(memory["confidence"] or 0.75), privacy=memory["privacy"], status=memory["status"], idempotency_key=f"generated:{external_id}:{len(memory_ids)}")
        result = repository.apply_memory_proposal(proposal)
        memory_ids.append(str(result["memory_id"]))
        version_id = str(result["version_id"])
    return {"user_id": user_id, "external_id": external_id, "avatar_id": avatar_id, "version_id": version_id, "source_document_ids": source_ids, "memory_ids": memory_ids}


async def _sync_vectors() -> dict[str, Any]:
    """消费本次生成用户产生的 outbox，并返回 Chroma 集合计数。"""
    vector_store = create_chroma_vector_store()
    total = {"processed": 0, "failed": 0}
    for _ in range(20):
        result = await sync_pending(vector_store, limit=100)
        total["processed"] += result["processed"]
        total["failed"] += result["failed"]
        if result["processed"] == 0 and result["failed"] == 0:
            break
    counts: dict[str, int] = {}
    for collection_name in ("avatar_memories", "source_documents"):
        try:
            counts[collection_name] = int(vector_store.client.get_collection(name=collection_name, embedding_function=vector_store.embedding_function).count())
        except Exception as exc:
            counts[collection_name] = -1
            total.setdefault("count_errors", []).append(f"{collection_name}: {exc}")
    return {"outbox": total, "chroma_counts": counts}


def _database_counts(user_ids: list[str]) -> list[dict[str, Any]]:
    """从 PostgreSQL 查询生成用户的最终画像、记忆和资料计数。"""
    with connect() as db:
        rows = db.execute("""SELECT u.id AS user_id,u.external_id,a.id AS avatar_id,
                count(DISTINCT m.id) AS memory_count,count(DISTINCT d.id) AS source_document_count,
                count(DISTINCT e.id) AS style_example_count
            FROM users u JOIN user_avatars a ON a.user_id=u.id
            LEFT JOIN avatar_memories m ON m.avatar_id=a.id
            LEFT JOIN source_documents d ON d.avatar_id=a.id
            LEFT JOIN avatar_style_examples e ON e.avatar_id=a.id
            WHERE u.id = ANY(%s) GROUP BY u.id,u.external_id,a.id ORDER BY u.external_id""", (user_ids,)).fetchall()
    return [dict(row) for row in rows]


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    """执行生成、PostgreSQL 写入、向量同步和结果汇总。"""
    request = _read_request(args.request, args.input_file)
    if not request:
        raise ValueError("生成要求不能为空")
    initialize_formal()
    generated = await _generate(request, args.count, args.model, args.model_response_file)
    persisted = [_write_user(item, request, index) for index, item in enumerate(generated, 1)]
    vector_result = {"skipped": True} if args.skip_vector else await _sync_vectors()
    user_ids = [item["user_id"] for item in persisted]
    model_values = load_model_values(model_env_path())
    configured_model = args.model or model_setting("LLM_MODEL", model_values)
    return {"ok": True, "generated_at": datetime.now(timezone.utc).isoformat(), "llm_model": configured_model, "request": request, "users": persisted, "postgres_counts": _database_counts(user_ids), "vector_sync": vector_result}


def main() -> None:
    """解析 CLI 参数并以 UTF-8 JSON 输出生成结果。"""
    parser = argparse.ArgumentParser(description="根据自然语言要求生成虚拟用户并写入 PostgreSQL + Chroma")
    parser.add_argument("request", nargs="?", help="自然语言生成要求；也可通过标准输入提供")
    parser.add_argument("--input-file", help="UTF-8 编码的自然语言要求文件")
    parser.add_argument("--count", type=int, default=1, help="生成用户数量，默认 1，最多 20")
    parser.add_argument("--model", help="覆盖 LLM_MODEL；密钥仍从模型配置读取")
    parser.add_argument("--model-response-file", help="使用 UTF-8 JSON 模型响应文件，便于离线复现；不调用 LLM")
    parser.add_argument("--skip-vector", action="store_true", help="仅用于离线诊断，跳过 Chroma 同步；正式数据准备不要使用")
    parser.add_argument("--output", help="将结果同时保存为 UTF-8 JSON 文件")
    args = parser.parse_args()
    args.count = max(1, min(args.count, 20))
    result = asyncio.run(_run(args))
    rendered = json.dumps(result, ensure_ascii=False, indent=2, default=str)
    print(rendered)
    if args.output:
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
