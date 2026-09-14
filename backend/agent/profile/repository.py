"""Transactional PostgreSQL repository for the collaborator avatar schema."""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4
from psycopg.types.json import Jsonb
from db.database import connect
from .proposals import ProfileProposal, ProposalError

def _now(): return datetime.now(timezone.utc)

class ProfileRepository:
    def initialize_avatar(self, *, user_id: str, identity: dict, personality: dict | None = None,
                          style: dict | None = None, policy: dict | None = None,
                          memory_rules: dict | None = None) -> dict[str, Any]:
        """Create the first complete active avatar version in one transaction."""
        with connect() as db:
            db.execute("INSERT INTO users(id) VALUES(%s) ON CONFLICT(id) DO UPDATE SET updated_at=now()", (user_id,))
            avatar = db.execute("INSERT INTO user_avatars(user_id,display_name,summary,status) VALUES(%s,%s,%s,'ready') ON CONFLICT(user_id) DO UPDATE SET updated_at=now() RETURNING id,current_version_id", (user_id, identity.get("display_name"), identity.get("summary"))).fetchone()
            if avatar["current_version_id"]:
                return {"avatar_id": str(avatar["id"]), "version_id": str(avatar["current_version_id"]), "status": "already_initialized"}
            version = db.execute("INSERT INTO avatar_versions(avatar_id,version_no,source_type,status,snapshot,created_by,activated_at) VALUES(%s,1,'llm_extract','active',%s,'system',now()) RETURNING id", (avatar["id"], Jsonb({"identity": identity, "personality": personality or {}, "style": style or {}, "policy": policy or {}, "memory_rules": memory_rules or {"top_k": 8}}))).fetchone()
            db.execute("UPDATE user_avatars SET current_version_id=%s WHERE id=%s", (version["id"], avatar["id"]))
            db.execute("INSERT INTO avatar_identity(avatar_version_id,display_name,summary,occupation,location,age,privacy_level,extra) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)", (version["id"], identity.get("display_name"), identity.get("summary"), identity.get("occupation"), identity.get("location"), identity.get("age"), identity.get("privacy_level", "private"), Jsonb(identity.get("extra", {}))))
            if personality:
                db.execute("INSERT INTO avatar_personality(avatar_version_id,model_name,scores,style_tags,confidence,inference_source,status) VALUES(%s,%s,%s,%s,%s,%s,%s)", (version["id"], personality.get("model_name", "big_five"), Jsonb(personality.get("scores", {})), Jsonb(personality.get("style_tags", [])), personality.get("confidence"), personality.get("inference_source", "inferred_from_user_data"), personality.get("status", "unconfirmed")))
            style = style or {}
            db.execute("INSERT INTO avatar_styles(avatar_version_id,tone,structure_rules,verbosity,technical_density,sentence_style,uncertainty_style,preferred_registers,avoid_rules,extra) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", (version["id"], Jsonb(style.get("tone", [])), Jsonb(style.get("structure_rules", [])), style.get("verbosity", "medium"), style.get("technical_density"), style.get("sentence_style"), style.get("uncertainty_style"), Jsonb(style.get("preferred_registers", [])), Jsonb(style.get("avoid_rules", [])), Jsonb(style.get("extra", {}))))
            policy = policy or {}
            db.execute("INSERT INTO avatar_policies(avatar_id,can_use_unconfirmed_memory,can_present_unconfirmed_as_fact,can_invent_user_experience,can_invent_user_opinion,must_show_uncertainty,must_keep_citations,sensitive_attributes_policy,external_action_requires_confirmation,custom_rules) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", (avatar["id"], policy.get("can_use_unconfirmed_memory", True), policy.get("can_present_unconfirmed_as_fact", False), policy.get("can_invent_user_experience", False), policy.get("can_invent_user_opinion", False), policy.get("must_show_uncertainty", True), policy.get("must_keep_citations", True), policy.get("sensitive_attributes_policy", "do_not_infer"), policy.get("external_action_requires_confirmation", True), Jsonb(policy.get("custom_rules", {}))))
            rules = memory_rules or {}
            db.execute("INSERT INTO avatar_memory_rules(avatar_id,top_k,use_vector_search,use_keyword_search,prefer_confirmed,prefer_recent_opinions,confidence_policy) VALUES(%s,%s,%s,%s,%s,%s,%s)", (avatar["id"], rules.get("top_k", 8), rules.get("use_vector_search", True), rules.get("use_keyword_search", True), rules.get("prefer_confirmed", True), rules.get("prefer_recent_opinions", True), Jsonb(rules.get("confidence_policy", {}))))
            return {"avatar_id": str(avatar["id"]), "version_id": str(version["id"]), "version_no": 1, "status": "initialized"}

    def add_memory_evidence(self, *, memory_id: str, source_document_id: str, quote: str, evidence_type: str = "user_original", relevance_score: float | None = None) -> str:
        with connect() as db:
            row = db.execute("INSERT INTO memory_evidence(memory_id,source_document_id,quote,evidence_type,relevance_score) VALUES(%s,%s,%s,%s,%s) ON CONFLICT(memory_id,source_document_id,quote) DO UPDATE SET relevance_score=EXCLUDED.relevance_score RETURNING id", (memory_id, source_document_id, quote, evidence_type, relevance_score)).fetchone()
            db.execute("UPDATE avatar_memories SET evidence_count=(SELECT count(*) FROM memory_evidence WHERE memory_id=%s),updated_at=now() WHERE id=%s", (memory_id, memory_id))
            return str(row["id"])
    def apply_memory_proposal(self, proposal: ProfileProposal) -> dict[str, Any]:
        proposal.validate()
        with connect() as db:
            avatar=db.execute("SELECT id,current_version_id FROM user_avatars WHERE id=%s AND user_id=%s FOR UPDATE",(proposal.avatar_id,proposal.user_id)).fetchone()
            if not avatar: raise ProposalError("avatar does not belong to user")
            idem=db.execute("SELECT version_id,target_id FROM avatar_change_logs WHERE avatar_id=%s AND operation=%s AND reason=%s LIMIT 1",(proposal.avatar_id,"agent_proposal",proposal.idempotency_key)).fetchone()
            if idem: return {"status":"duplicate","version_id":str(idem["version_id"]),"memory_id":str(idem["target_id"])}
            if proposal.base_version_id and str(avatar["current_version_id"]) != proposal.base_version_id: raise ProposalError("avatar version conflict")
            old_id=avatar["current_version_id"]
            old_no=db.execute("SELECT COALESCE(MAX(version_no),0) AS n FROM avatar_versions WHERE avatar_id=%s",(proposal.avatar_id,)).fetchone()["n"]
            previous=db.execute("SELECT snapshot FROM avatar_versions WHERE id=%s", (old_id,)).fetchone() if old_id else None
            snapshot=dict((previous or {}).get("snapshot") or {})
            snapshot["last_change"]={"proposal_type":proposal.proposal_type,"payload":proposal.payload,"source_refs":proposal.source_refs}
            version=db.execute("""INSERT INTO avatar_versions(avatar_id,version_no,source_type,base_version_id,status,change_summary, snapshot,created_by)
                VALUES(%s,%s,'system_merge',%s,'draft',%s,%s,'system') RETURNING id,version_no""",(proposal.avatar_id,old_no+1,old_id,proposal.proposal_type,Jsonb(snapshot))).fetchone()
            if old_id: db.execute("UPDATE avatar_versions SET status='superseded' WHERE id=%s",(old_id,))
            db.execute("UPDATE avatar_versions SET status='active', activated_at=now() WHERE id=%s",(version["id"],))
            if old_id:
                db.execute("INSERT INTO avatar_identity(avatar_version_id,display_name,summary,occupation,location,age,privacy_level,extra) SELECT %s,display_name,summary,occupation,location,age,privacy_level,extra FROM avatar_identity WHERE avatar_version_id=%s", (version["id"], old_id))
                db.execute("INSERT INTO avatar_personality(avatar_version_id,model_name,scores,style_tags,confidence,inference_source,status) SELECT %s,model_name,scores,style_tags,confidence,inference_source,status FROM avatar_personality WHERE avatar_version_id=%s", (version["id"], old_id))
                db.execute("INSERT INTO avatar_styles(avatar_version_id,tone,structure_rules,verbosity,technical_density,sentence_style,uncertainty_style,preferred_registers,avoid_rules,extra) SELECT %s,tone,structure_rules,verbosity,technical_density,sentence_style,uncertainty_style,preferred_registers,avoid_rules,extra FROM avatar_styles WHERE avatar_version_id=%s", (version["id"], old_id))
            db.execute("UPDATE user_avatars SET current_version_id=%s,updated_at=now() WHERE id=%s",(version["id"],proposal.avatar_id))
            p=proposal.payload
            memory=db.execute("""INSERT INTO avatar_memories(avatar_id,version_id,memory_type,topic,content,structured_data,level,confidence,status,privacy,evidence_count)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,0) RETURNING id""",(proposal.avatar_id,version["id"],p["memory_type"],p.get("topic"),p["content"],Jsonb(p.get("structured_data",p)),p["level"],proposal.confidence,proposal.status,proposal.privacy)).fetchone()
            # Link only existing source documents owned by this avatar; the
            # original answer is retained and can be audited independently.
            for source_ref in proposal.source_refs:
                source = db.execute("SELECT id FROM source_documents WHERE id=%s AND avatar_id=%s", (source_ref, proposal.avatar_id)).fetchone()
                if source:
                    db.execute("INSERT INTO memory_evidence(memory_id,source_document_id,quote,evidence_type,relevance_score) VALUES(%s,%s,%s,'inference',%s) ON CONFLICT(memory_id,source_document_id,quote) DO NOTHING", (memory["id"], source["id"], p["content"], proposal.confidence))
            db.execute("UPDATE avatar_memories SET evidence_count=(SELECT count(*) FROM memory_evidence WHERE memory_id=%s) WHERE id=%s", (memory["id"], memory["id"]))
            db.execute("""UPDATE avatar_versions SET snapshot = snapshot || jsonb_build_object(
                    'memories', COALESCE(snapshot->'memories','[]'::jsonb) || jsonb_build_array(
                    jsonb_build_object('id', %s::text, 'memory_type', %s::text, 'topic', %s::text,
                                       'content', %s::text, 'level', %s::text, 'confidence', %s::numeric,
                                       'status', %s::text, 'privacy', %s::text))) WHERE id=%s""",
                (str(memory["id"]), p["memory_type"], p.get("topic"), p["content"],
                 p["level"], proposal.confidence, proposal.status, proposal.privacy, version["id"]))
            db.execute("INSERT INTO avatar_change_logs(avatar_id,version_id,operator_type,operation,target_type,target_id,after_data,reason) VALUES(%s,%s,'system','agent_proposal','avatar_memory',%s,%s,%s)",(proposal.avatar_id,version["id"],memory["id"],Jsonb(p),proposal.idempotency_key))
            db.execute("""INSERT INTO vector_sync_outbox(avatar_id,entity_type,entity_id,operation,collection,payload)
                VALUES(%s,'avatar_memory',%s,'upsert','avatar_memories',%s)
                ON CONFLICT DO NOTHING""",(proposal.avatar_id,memory["id"],Jsonb({"memory_id":str(memory["id"]),"avatar_id":proposal.avatar_id})))
            return {"status":"applied","version_id":str(version["id"]),"memory_id":str(memory["id"]),"version_no":version["version_no"]}

    def write_source(self, *, user_id:str, avatar_id:str, platform:str, document_type:str, content:str, source_url:str|None=None, external_id:str|None=None, metadata:dict|None=None) -> str:
        with connect() as db:
            owner=db.execute("SELECT 1 FROM user_avatars WHERE id=%s AND user_id=%s AND status <> 'archived'",(avatar_id,user_id)).fetchone()
            if not owner: raise ProposalError("avatar does not belong to user")
            import hashlib
            content_hash=hashlib.sha256(content.encode('utf-8')).hexdigest()
            row=db.execute("""INSERT INTO source_documents(user_id,avatar_id,platform,external_id,document_type,content,source_url,content_hash,metadata)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(platform,external_id) DO UPDATE SET content=EXCLUDED.content,content_hash=EXCLUDED.content_hash,metadata=EXCLUDED.metadata RETURNING id""",(user_id,avatar_id,platform,external_id,document_type,content,source_url,content_hash,Jsonb(metadata or {}))).fetchone()
            # Vector indexing is asynchronous and never blocks the source-of-truth write.
            db.execute("""INSERT INTO vector_sync_outbox(avatar_id,entity_type,entity_id,operation,collection,payload)
                VALUES(%s,'source_document',%s,'upsert','source_documents',%s)
                ON CONFLICT DO NOTHING""", (avatar_id, row["id"], Jsonb({"document_id": str(row["id"]), "avatar_id": avatar_id})))
            return str(row["id"])
