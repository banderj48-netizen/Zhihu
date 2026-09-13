"""Traditional-backend write functions. These are not exposed as Agent tools."""
from __future__ import annotations
from typing import Any
from .repository import ProfileRepository
from .chat_repository import ChatRepository

def initialize_profile(**kwargs) -> dict[str, Any]:
    return ProfileRepository().initialize_avatar(**kwargs)

def write_source_document(**kwargs) -> str:
    return ProfileRepository().write_source(**kwargs)

def create_chat_conversation(*, conversation_type: str = "direct", title: str | None = None) -> str:
    return ChatRepository().create_conversation(conversation_type, title)

def write_chat_message(*, conversation_id: str, participant_id: str, content: str,
                       client_message_id: str | None = None, message_type: str = "text",
                       metadata: dict | None = None) -> dict[str, Any]:
    return ChatRepository().append_message(conversation_id, participant_id, content,
        client_message_id=client_message_id, message_type=message_type, metadata=metadata)

def record_memory_evidence(**kwargs) -> str:
    return ProfileRepository().add_memory_evidence(**kwargs)

__all__ = ["initialize_profile", "write_source_document", "create_chat_conversation",
           "write_chat_message", "record_memory_evidence"]
