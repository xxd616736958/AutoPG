"""
Unified interaction protocol. Agent asks questions via InteractionRequest.
Frontend (TUI/Web/remote) renders and returns InteractionResponse.
Agent only sees Response — doesn't know or care which frontend rendered it.
"""
from dataclasses import dataclass, field
from typing import Optional
import uuid


@dataclass
class InteractionRequest:
    """Agent needs user input. Frontend decides how to render."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    type: str = "confirm"        # confirm | select | approve_sql
    message: str = ""            # Human-readable question
    context: dict = field(default_factory=dict)  # Extra data for rendering
    options: Optional[list[str]] = None  # For 'select' type


@dataclass
class InteractionResponse:
    """User's answer. Same format regardless of frontend."""
    request_id: str
    action: str = "reject"       # accept | reject | select_0 | select_1 | custom
    value: Optional[str] = None  # Custom input for 'custom' action
