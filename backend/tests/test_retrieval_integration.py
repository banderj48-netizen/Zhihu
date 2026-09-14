"""Real PostgreSQL collaborator-schema write/read integration; vector IDs are controlled fixtures.

No production tables are touched. No Chroma/embedding quality is claimed here.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import re
import unittest
from unittest.mock import patch
from uuid import uuid4

from psycopg import sql
from psycopg.types.json import Jsonb
from db.database import connect
from agent.profile.repository import ProfileRepository
from agent.profile.proposals import ProfileProposal, ProposalError
from agent.profile.chat_repository import ChatRepository
from agent.retrieval.service import (
    PostgresRetrievalRepository, analyze_question, build_context, index_memory,
    index_source_document_chunk, index_chat_message, search_long_memories,
    search_source_documents, search_chat_history, limit_memory_groups,
)
try:
    from test_postgres import BASE_URL, schema_url
except ModuleNotFoundError:
    from backend.tests.test_postgres import BASE_URL, schema_url


class CandidateVector:
    """Contract double. Deliberately ignores filters to test PostgreSQL authority."""
    def __init__(self):
        self.collections = {}

    async def upsert(self, collection, ids, documents, metadatas):
        rows = self.collections.setdefault(collection, {})
        for key, metadata in zip(ids, metadatas):
            rows[key] = {"id": key, "semantic_score": 0.9, "metadata": metadata}

    async def search(self, collection, query_text, *, where=None, limit=20):
        return list(self.collections.get(collection, {}).values())[:limit]

    async def delete(self, collection, ids):
        for key in ids:
            self.collections.get(collection, {}).pop(key, None)


@unittest.skipUnless(BASE_URL, "Set TWINLOOP_TEST_DATABASE_URL for PostgreSQL integration")
class RetrievalWriteTests(unittest.TestCase):
    def setUp(self):
        self.schema = "test_rag_" + uuid4().hex
        self.addCleanup(self.cleanup_schema)
        with connect(BASE_URL) as db:
            db.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(self.schema)))
            for name in ("postgresql_zhihu_schema.sql", "postgresql_chat_schema.sql", "postgresql_profile_outbox.sql"):
                source = (Path(__file__).parents[1] / "db" / name).read_text(encoding="utf-8-sig")
                source = re.sub(r"(?m)^(BEGIN;|COMMIT;|CREATE EXTENSION IF NOT EXISTS pgcrypto;)\s*$", "", source)
                db.execute(source.replace("public.", self.schema + "."))
        env = patch.dict(os.environ, {"DATABASE_URL": schema_url(BASE_URL, self.schema)})
        env.start()
        self.addCleanup(env.stop)
        self.writer = ProfileRepository()
        self.reader = PostgresRetrievalRepository(connect)
        self.vector = CandidateVector()
        self.user, self.avatar, self.version = self.seed_avatar()

    def cleanup_schema(self):
        self.assertRegex(self.schema, r"^test_rag_[a-f0-9]{32}$")
        with connect(BASE_URL) as db:
            db.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(self.schema)))

    def seed_avatar(self):
        with connect() as db:
            user = db.execute("INSERT INTO users DEFAULT VALUES RETURNING id").fetchone()["id"]
            avatar = db.execute("INSERT INTO user_avatars(user_id,status) VALUES (%s,'ready') RETURNING id", (user,)).fetchone()["id"]
            version = db.execute("INSERT INTO avatar_versions(avatar_id,version_no,status,snapshot) VALUES (%s,1,'active',%s) RETURNING id", (avatar, Jsonb({"identity": {"occupation": "工程师"}, "memories": []}))).fetchone()["id"]
            db.execute("UPDATE user_avatars SET current_version_id=%s WHERE id=%s", (version, avatar))
            db.execute("INSERT INTO avatar_identity(avatar_version_id,occupation) VALUES (%s,'工程师')", (version,))
            db.execute("INSERT INTO avatar_personality(avatar_version_id,model_name,scores) VALUES (%s,'big_five',%s)", (version, Jsonb({"openness": 7.0})))
            db.execute("INSERT INTO avatar_styles(avatar_version_id,tone) VALUES (%s,%s)", (version, Jsonb(["直接"])))
            db.execute("INSERT INTO avatar_policies(avatar_id) VALUES (%s)", (avatar,))
        return str(user), str(avatar), str(version)

    def proposal(self, **overrides):
        data = dict(user_id=self.user, avatar_id=self.avatar, base_version_id=self.version,
                    proposal_type="propose_behavior_memory", payload={"memory_type": "behavior", "level": "middle", "topic": "原神", "content": "先核对原神剧情原文，再表达不同意见。", "structured_data": {"conditions": ["剧情争议"]}}, confidence=0.8)
        data.update(overrides)
        return ProfileProposal(**data)

    def index_saved_memory(self, memory_id):
        with connect() as db:
            row = db.execute("SELECT * FROM avatar_memories WHERE id=%s", (memory_id,)).fetchone()
        asyncio.run(index_memory(row, self.vector))

    def test_version_write_then_build_context_preserves_fixed_profile(self):
        result = self.writer.apply_memory_proposal(self.proposal())
        self.index_saved_memory(result["memory_id"])
        context = asyncio.run(build_context(self.user, "原神", self.reader, self.vector))
        self.assertEqual(str(context["profile"]["avatar_id"]), self.avatar)
        self.assertEqual(context["profile"]["occupation"], "工程师")
        self.assertEqual(context["profile"]["personality_scores"], {"openness": 7.0})
        self.assertEqual(context["profile"]["style_tone"], ["直接"])
        memories = context["retrieved_memories"]["behavior_memories"]
        self.assertEqual([str(m["memory_id"]) for m in memories], [result["memory_id"]])
        self.assertEqual(memories[0]["structured_data"]["conditions"], ["剧情争议"])
        self.assertEqual(memories[0]["status"], "unconfirmed")
        with connect() as db:
            self.assertEqual(db.execute("SELECT count(*) AS n FROM avatar_versions WHERE avatar_id=%s AND status='active'", (self.avatar,)).fetchone()["n"], 1)
            self.assertEqual(db.execute("SELECT status FROM vector_sync_outbox").fetchone()["status"], "pending")
            snapshot = db.execute("SELECT snapshot FROM avatar_versions WHERE id=%s", (result["version_id"],)).fetchone()["snapshot"]
            self.assertEqual(snapshot["identity"]["occupation"], "工程师")

    def test_final_memory_context_has_global_ten_item_limit(self):
        """最终上下文的记忆上限是全局 10 条，而不是每类各 10 条。"""
        groups = {
            "experiences": [{"memory_id": f"e{i}", "relevance_score": 1.0 - i / 100} for i in range(6)],
            "opinions": [{"memory_id": f"o{i}", "relevance_score": 0.9 - i / 100} for i in range(6)],
            "behavior_memories": [],
            "expertise": [{"memory_id": f"x{i}", "relevance_score": 0.8 - i / 100} for i in range(6)],
            "interests": [],
        }
        limited = limit_memory_groups(groups)
        self.assertEqual(sum(len(rows) for rows in limited.values()), 10)
        self.assertEqual(limited["experiences"][0]["memory_id"], "e0")
        self.assertEqual(limited["opinions"][0]["memory_id"], "o0")

    def test_idempotent_retry_and_stale_version(self):
        proposal = self.proposal()
        result = self.writer.apply_memory_proposal(proposal)
        duplicate = self.writer.apply_memory_proposal(proposal)
        self.assertEqual(duplicate["memory_id"], result["memory_id"])
        with self.assertRaises(ProposalError):
            self.writer.apply_memory_proposal(self.proposal())

    def test_vector_candidates_rechecked_for_owner_status_time(self):
        result = self.writer.apply_memory_proposal(self.proposal())
        self.index_saved_memory(result["memory_id"])
        other_user, other_avatar, other_version = self.seed_avatar()
        other = self.writer.apply_memory_proposal(self.proposal(user_id=other_user, avatar_id=other_avatar, base_version_id=other_version))
        self.index_saved_memory(other["memory_id"])
        asyncio.run(self.vector.upsert("avatar_memories", [str(uuid4())], ["missing"], [{}]))
        for column, value in (("status", "rejected"), ("privacy", "sensitive"), ("valid_until", "2000-01-01T00:00:00Z")):
            with connect() as db:
                if column == "status":
                    db.execute("UPDATE avatar_memories SET status=%s,privacy='private',valid_until=NULL WHERE id=%s", (value, result["memory_id"]))
                elif column == "privacy":
                    db.execute("UPDATE avatar_memories SET status='unconfirmed',privacy=%s,valid_until=NULL WHERE id=%s", (value, result["memory_id"]))
                else:
                    db.execute("UPDATE avatar_memories SET status='unconfirmed',privacy='private',valid_until=%s WHERE id=%s", (value, result["memory_id"]))
            groups = asyncio.run(search_long_memories(self.reader, self.vector, self.avatar, analyze_question("原神")))
            self.assertFalse(any(groups.values()))

    def test_source_write_hash_and_chunk_id_roundtrip(self):
        document = self.writer.write_source(user_id=self.user, avatar_id=self.avatar, platform="test", document_type="answer", content="原神剧情应该结合原文讨论。", external_id="test_answer", source_url="https://example.invalid/source")
        asyncio.run(index_source_document_chunk({"document_id": document, "chunk_id": "chunk_1", "avatar_id": self.avatar, "content": "原神剧情"}, self.vector))
        rows = asyncio.run(search_source_documents(self.reader, self.vector, self.avatar, analyze_question("different query")))
        self.assertEqual(str(rows[0]["document_id"]), document)
        self.assertGreater(rows[0]["relevance_score"], 0)
        self.assertIn("原神", rows[0]["content"])

    def test_chat_append_concurrent_idempotent_and_retrieve_peer(self):
        chat = ChatRepository()
        cid = chat.create_conversation(title="原神讨论")
        other_user, other_avatar, _ = self.seed_avatar()
        with connect() as db:
            own = db.execute("INSERT INTO chat_participants(conversation_id,avatar_id) VALUES (%s,%s) RETURNING id", (cid, self.avatar)).fetchone()["id"]
            peer = db.execute("INSERT INTO chat_participants(conversation_id,avatar_id) VALUES (%s,%s) RETURNING id", (cid, other_avatar)).fetchone()["id"]
        msg = chat.append_message(cid, str(peer), "原神剧情先核对原文", client_message_id="same")
        retry = chat.append_message(cid, str(peer), "原神剧情先核对原文", client_message_id="same")
        self.assertEqual(msg["message_id"], retry["message_id"])
        with ThreadPoolExecutor(max_workers=3) as pool:
            messages = list(pool.map(lambda i: chat.append_message(cid, str(own), f"上下文 {i}"), range(3)))
        self.assertEqual(len({m["sequence_no"] for m in messages}), 3)
        asyncio.run(index_chat_message({**msg, "avatar_id": other_avatar, "conversation_id": cid, "content": "原神剧情", "participant_id": str(peer)}, self.vector))
        rows = asyncio.run(search_chat_history(self.reader, self.vector, self.avatar, analyze_question("原神"), conversation_id=cid))
        self.assertIn(msg["message_id"], [str(r["matched_message_id"]) for r in rows])
        stranger = self.seed_avatar()[1]
        self.assertEqual(asyncio.run(search_chat_history(self.reader, self.vector, stranger, analyze_question("原神"), conversation_id=cid)), [])
        with connect() as db:
            db.execute("UPDATE chat_messages SET deleted_at=now() WHERE id=%s", (msg["message_id"],))
        self.assertEqual(asyncio.run(search_chat_history(self.reader, self.vector, self.avatar, analyze_question("原神"), conversation_id=cid)), [])

    def test_source_owner_cannot_be_forged(self):
        other_user, other_avatar, _ = self.seed_avatar()
        with self.assertRaises(ProposalError):
            self.writer.write_source(user_id=self.user, avatar_id=other_avatar, platform="test", document_type="answer", content="invalid owner")
