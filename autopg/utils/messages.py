"""
Message helpers for AutoPG.
Architecturally mirrors AutoPG's utils/messages.ts.
"""
from typing import Any, Optional
from datetime import datetime
import uuid

from langchain_core.messages import (
    BaseMessage,
    HumanMessage,
    AIMessage,
    ToolMessage,
    SystemMessage,
)


def create_user_message(
    content: str,
    is_meta: bool = False,
    tool_use_result: Optional[str] = None,
) -> HumanMessage:
    """Create a user message, mirroring createUserMessage in messages.ts."""
    msg = HumanMessage(
        content=content,
        additional_kwargs={
            "is_meta": is_meta,
            "timestamp": datetime.now().isoformat(),
            "uuid": str(uuid.uuid4()),
        },
    )
    if tool_use_result:
        msg.additional_kwargs["tool_use_result"] = tool_use_result
    return msg


def create_assistant_message(
    content: str,
    stop_reason: Optional[str] = None,
    tool_calls: Optional[list] = None,
    is_api_error_message: bool = False,
) -> AIMessage:
    """Create an assistant message."""
    msg = AIMessage(
        content=content,
        additional_kwargs={
            "stop_reason": stop_reason,
            "timestamp": datetime.now().isoformat(),
            "uuid": str(uuid.uuid4()),
            "is_api_error_message": is_api_error_message,
        },
    )
    if tool_calls:
        msg.additional_kwargs["tool_calls"] = tool_calls
        msg.tool_calls = tool_calls
    return msg


def create_assistant_api_error_message(
    content: str,
    error: str = "",
) -> AIMessage:
    """Create an API error assistant message, mirroring createAssistantAPIErrorMessage."""
    return AIMessage(
        content=content,
        additional_kwargs={
            "is_api_error_message": True,
            "api_error": error,
            "timestamp": datetime.now().isoformat(),
            "uuid": str(uuid.uuid4()),
        },
    )


def create_system_message(
    content: str,
    subtype: str = "info",
) -> SystemMessage:
    """Create a system message."""
    return SystemMessage(
        content=content,
        additional_kwargs={
            "subtype": subtype,
            "timestamp": datetime.now().isoformat(),
            "uuid": str(uuid.uuid4()),
        },
    )


def create_user_interruption_message(tool_use: bool = False) -> HumanMessage:
    """Create a user interruption message."""
    return HumanMessage(
        content="[Request interrupted by user]",
        additional_kwargs={
            "is_interruption": True,
            "tool_use": tool_use,
            "timestamp": datetime.now().isoformat(),
            "uuid": str(uuid.uuid4()),
        },
    )


def normalize_messages_for_api(
    messages: list[BaseMessage],
) -> list[BaseMessage]:
    """Normalize messages for API consumption, mirroring normalizeMessagesForAPI."""
    # Strip messages that shouldn't be sent to the API
    result = []
    for msg in messages:
        additional = getattr(msg, "additional_kwargs", {}) or {}
        # Skip meta messages
        if additional.get("is_meta"):
            continue
        # Skip interruption messages
        if additional.get("is_interruption"):
            continue
        result.append(msg)
    return result


def get_messages_after_compact_boundary(
    messages: list[BaseMessage],
) -> list[BaseMessage]:
    """Get messages after the last compact boundary, mirroring getMessagesAfterCompactBoundary."""
    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]
        additional = getattr(msg, "additional_kwargs", {}) or {}
        if additional.get("subtype") == "compact_boundary":
            return list(messages[i + 1:])
    return list(messages)


def is_api_error_message(msg: BaseMessage) -> bool:
    """Check if a message is an API error."""
    additional = getattr(msg, "additional_kwargs", {}) or {}
    return additional.get("is_api_error_message", False)
