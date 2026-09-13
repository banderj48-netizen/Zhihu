"""Safe Agent-facing write tools.

These functions accept structured arguments and delegate all persistence to the
traditional backend repository.  They never expose a database connection.
"""
from __future__ import annotations
from typing import Any
from .proposals import ProfileProposal
from .repository import ProfileRepository

def _memory(kind: str, *, user_id: str, avatar_id: str, base_version_id: str | None,
            topic: str | None, content: str, level: str, structured_data: dict[str, Any] | None = None,
            source_refs: list[str] | None = None, confidence: float | None = None,
            privacy: str = "private", status: str = "unconfirmed", idempotency_key: str | None = None) -> dict[str, Any]:
    p = ProfileProposal(user_id=user_id, avatar_id=avatar_id, base_version_id=base_version_id,
        proposal_type=f"propose_{kind}_memory",
        payload={"memory_type": kind, "topic": topic, "content": content,
                 "level": level, "structured_data": structured_data or {}},
        source_refs=source_refs or [], confidence=confidence, privacy=privacy, status=status,
        idempotency_key=idempotency_key or ProfileProposal.__dataclass_fields__["idempotency_key"].default_factory())
    return ProfileRepository().apply_memory_proposal(p)

def propose_avatar_memory(**kwargs):
    return _memory(kwargs.pop("memory_type"), **kwargs)

def propose_opinion_memory(**kwargs):
    return _memory("opinion", **kwargs)

def propose_behavior_memory(**kwargs):
    return _memory("behavior", **kwargs)

def propose_expertise_memory(**kwargs):
    return _memory("expertise", **kwargs)

def propose_interest_memory(**kwargs):
    return _memory("interest", **kwargs)

def propose_fact_memory(**kwargs):
    return _memory("fact", **kwargs)

def propose_experience_memory(**kwargs):
    return _memory("experience", **kwargs)

def propose_memory_evidence(*, memory_id: str, source_document_id: str, quote: str,
                            evidence_type: str = "user_original", relevance_score: float | None = None):
    return {"evidence_id": ProfileRepository().add_memory_evidence(
        memory_id=memory_id, source_document_id=source_document_id, quote=quote,
        evidence_type=evidence_type, relevance_score=relevance_score)}

__all__ = ["propose_avatar_memory", "propose_opinion_memory", "propose_behavior_memory",
           "propose_expertise_memory", "propose_interest_memory", "propose_fact_memory",
           "propose_experience_memory", "propose_memory_evidence"]
