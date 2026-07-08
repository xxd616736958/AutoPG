"""
AgentContext — Runtime.context type for LangGraph context_schema.
Data shared across all middleware, graph nodes, and tools.
"""
from dataclasses import dataclass, field
from typing import Optional, Callable, Any


@dataclass
class AgentContext:
    """LangGraph Runtime.context payload. Type-safe context passed through all layers."""
    session_id: str = ""
    cwd: str = ""
    provider: str = "deepseek"
    model: str = "deepseek-v4-flash"
    permission_mode: str = "default"
    auto_save: bool = True
    is_non_interactive: bool = False
    max_turns: int = 100

    # Infrastructure
    collapse_manager: Optional[Any] = None
    compact_manager: Optional[Any] = None
    file_cache: Optional[Any] = None
    total_usage: dict = field(default_factory=lambda: {"input_tokens": 0, "output_tokens": 0})
    result_temp_dir: str = ""
    _parent_engine: Optional[Any] = None

    # Callbacks
    on_stream_token: Optional[Callable[[str], None]] = None
    on_tool_start: Optional[Callable[[str, str], None]] = None
    on_tool_end: Optional[Callable[[str, str], None]] = None
    on_permission_check: Optional[Callable[[str, bool, str], bool]] = None
