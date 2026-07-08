"""
Agent state definition for AutoPG.
Mirrors the QueryEngine state and query loop state from AutoPG.
"""
from typing import TypedDict, Annotated, Any, Optional, Sequence
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
import uuid


class ToolPermissionContext(TypedDict, total=False):
    """Permission context for tool execution."""
    mode: str  # 'default', 'accept_edits', 'bypass', 'plan'
    additional_working_directories: dict
    always_allow_rules: dict
    always_deny_rules: dict
    always_ask_rules: dict
    is_bypass_permissions_mode_available: bool


class ToolUseContext(TypedDict, total=False):
    """Context passed to tool calls, matching AutoPG's ToolUseContext."""
    cwd: str
    tools: list
    verbose: bool
    main_loop_model: str
    thinking_config: dict
    is_non_interactive_session: bool
    permission_mode: str
    agent_definitions: dict
    messages: list
    abort_signal: bool
    session_id: str
    turn_count: int
    max_budget_usd: Optional[float]
    custom_system_prompt: Optional[str]
    append_system_prompt: Optional[str]
    discovered_skill_names: set
    loaded_nested_memory_paths: set
    nested_memory_attachment_triggers: set


class AgentState(TypedDict):
    """The core state that flows through the LangGraph agent graph.

    Mirrors the State type in query.ts and QueryEngine's mutable state.
    """
    # Messages in the conversation (with add_messages reducer for proper merging)
    messages: Annotated[Sequence[BaseMessage], add_messages]

    # System prompt parts
    system_prompt: str
    user_context: dict
    system_context: dict

    # Tool configuration
    tools: list
    tool_use_context: ToolUseContext

    # Loop control
    turn_count: int
    max_turns: Optional[int]
    should_continue: bool

    # Streaming / abort
    abort_signal: bool
    stream_events: list

    # Tracking
    session_id: str
    model: str
    fallback_model: Optional[str]

    # Budget
    max_budget_usd: Optional[float]
    total_usage: dict

    # Attachments / metadata
    permission_denials: list
    structured_output: Optional[dict]

    # Auto-compact tracking (mirrors AutoCompactTrackingState)
    auto_compact_tracking: Optional[dict]

    # Recovery state
    max_output_tokens_recovery_count: int
    has_attempted_reactive_compact: bool
    max_output_tokens_override: Optional[int]

    # Hook state
    stop_hook_active: bool

    # Terminal / result
    terminal_reason: Optional[str]
    last_stop_reason: Optional[str]

    # Skills
    discovered_skill_names: set
    loaded_nested_memory_paths: set


def create_initial_state(
    messages: Optional[list] = None,
    system_prompt: str = "",
    user_context: Optional[dict] = None,
    system_context: Optional[dict] = None,
    tools: Optional[list] = None,
    model: str = "deepseek-v4-flash",
    fallback_model: Optional[str] = None,
    max_turns: Optional[int] = None,
    max_budget_usd: Optional[float] = None,
    cwd: str = "",
    permission_mode: str = "default",
    is_non_interactive_session: bool = False,
) -> AgentState:
    """Create the initial agent state, similar to QueryEngine constructor."""
    return AgentState(
        messages=messages or [],
        system_prompt=system_prompt,
        user_context=user_context or {},
        system_context=system_context or {},
        tools=tools or [],
        tool_use_context=ToolUseContext(
            cwd=cwd,
            tools=tools or [],
            verbose=False,
            main_loop_model=model,
            thinking_config={"type": "adaptive"},
            is_non_interactive_session=is_non_interactive_session,
            permission_mode=permission_mode,
            agent_definitions={},
            messages=[],
            abort_signal=False,
            session_id=str(uuid.uuid4()),
            turn_count=0,
            max_budget_usd=max_budget_usd,
            discovered_skill_names=set(),
            loaded_nested_memory_paths=set(),
            nested_memory_attachment_triggers=set(),
        ),
        turn_count=0,
        max_turns=max_turns,
        should_continue=True,
        abort_signal=False,
        stream_events=[],
        session_id=str(uuid.uuid4()),
        model=model,
        fallback_model=fallback_model,
        max_budget_usd=max_budget_usd,
        total_usage={"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0, "cache_creation_tokens": 0},
        permission_denials=[],
        structured_output=None,
        auto_compact_tracking=None,
        max_output_tokens_recovery_count=0,
        has_attempted_reactive_compact=False,
        max_output_tokens_override=None,
        stop_hook_active=False,
        terminal_reason=None,
        last_stop_reason=None,
        discovered_skill_names=set(),
        loaded_nested_memory_paths=set(),
    )
