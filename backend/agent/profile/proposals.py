"""Validated write proposals emitted by Agent tools.

The Agent never receives a database connection. Traditional backend code
validates and applies these immutable proposals.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

MEMORY_TYPES = {"fact", "experience", "opinion", "behavior", "expertise", "interest", "stance", "reasoning_observation", "knowledge_signal"}
LEVELS = {"deep", "middle", "shallow"}
PRIVACY = {"private", "public", "sensitive"}

class ProposalError(ValueError): pass

@dataclass(frozen=True)
class ProfileProposal:
    user_id: str
    avatar_id: str
    base_version_id: str | None
    proposal_type: str
    payload: dict[str, Any]
    source_refs: list[str] = field(default_factory=list)
    confidence: float | None = None
    privacy: str = "private"
    status: str = "unconfirmed"
    request_id: str = field(default_factory=lambda: "req_" + uuid4().hex)
    idempotency_key: str = field(default_factory=lambda: "idem_" + uuid4().hex)

    def validate(self) -> None:
        if not self.user_id or not self.avatar_id or not self.proposal_type:
            raise ProposalError("user_id, avatar_id and proposal_type are required")
        if self.privacy not in PRIVACY: raise ProposalError("invalid privacy")
        if self.status not in {"confirmed", "unconfirmed"}: raise ProposalError("invalid status")
        if self.confidence is not None and not 0 <= self.confidence <= 1: raise ProposalError("confidence must be 0..1")
        if self.proposal_type.endswith("memory") or self.proposal_type in {"propose_avatar_memory", "propose_opinion_memory", "propose_behavior_memory"}:
            kind=self.payload.get("memory_type"); level=self.payload.get("level")
            if kind not in MEMORY_TYPES: raise ProposalError("invalid memory_type")
            if level not in LEVELS: raise ProposalError("invalid memory level")
            if not self.payload.get("content"): raise ProposalError("memory content is required")
