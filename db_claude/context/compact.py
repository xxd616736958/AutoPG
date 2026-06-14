"""
Context compaction for db-claude.
Architecturally mirrors Claude Code's compaction system (src/services/compact/).
Handles automatic context summarization to stay within model context limits.
"""
from typing import Optional
from langchain_core.messages import BaseMessage


class CompactManager:
    """
    Manages context compaction — summarization of conversation history
    when approaching context limits. Mirrors Claude Code's auto-compact
    and micro-compact systems.
    """

    # Token thresholds (mirrors Claude Code's AUTO_COMPACT_THRESHOLD)
    AUTO_COMPACT_WARNING_THRESHOLD = 0.75   # 75% of context window
    AUTO_COMPACT_BLOCKING_THRESHOLD = 0.95  # 95% of context window

    def __init__(self, model_name: str = "claude-sonnet-4-6"):
        self.model_name = model_name
        self.context_limit = self._get_context_limit(model_name)
        self.compaction_count = 0

    def _get_context_limit(self, model_name: str) -> int:
        """Get the context window size for a model."""
        limits = {
            "claude-opus-4-6": 200000,
            "claude-sonnet-4-6": 200000,
            "claude-haiku-4-5-20251001": 200000,
            "claude-sonnet-4-5": 200000,
            "claude-opus-4-5": 200000,
        }
        # Default to 200k for Claude 4+ models
        return limits.get(model_name, 200000)

    def estimate_token_count(self, messages: list[BaseMessage]) -> int:
        """
        Estimate token count for messages.
        Uses a simple character-based heuristic (4 chars ≈ 1 token).
        """
        total_tokens = 0
        for msg in messages:
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            total_tokens += len(content) // 4

            # Account for message overhead
            total_tokens += 4  # Role and formatting overhead

            # Tool calls overhead
            tool_calls = getattr(msg, "tool_calls", []) or []
            for tc in tool_calls:
                tc_str = str(tc.get("args", {}))
                total_tokens += len(tc_str) // 4 + 10  # Function call overhead

        return total_tokens

    def should_compact(self, messages: list[BaseMessage]) -> dict:
        """Check if compaction is needed based on token count."""
        token_count = self.estimate_token_count(messages)
        warning_threshold = int(self.context_limit * self.AUTO_COMPACT_WARNING_THRESHOLD)
        blocking_threshold = int(self.context_limit * self.AUTO_COMPACT_BLOCKING_THRESHOLD)

        return {
            "token_count": token_count,
            "context_limit": self.context_limit,
            "usage_ratio": token_count / self.context_limit,
            "is_at_warning": token_count >= warning_threshold,
            "is_at_blocking_limit": token_count >= blocking_threshold,
            "should_compact": token_count >= warning_threshold,
        }

    def compact_messages(self, messages: list[BaseMessage], keep_last: int = 20) -> list[BaseMessage]:
        """
        Simple compaction: keep system message + recent messages.
        In production, this would use a summary model like Haiku.
        """
        if len(messages) <= keep_last:
            return messages

        self.compaction_count += 1

        # Keep first message (usually system prompt), and last N messages
        first = messages[0:1] if messages else []
        recent = messages[-keep_last:]

        # Create a compaction boundary marker
        from langchain_core.messages import SystemMessage

        boundary = SystemMessage(
            content=f"[Context compacted #{self.compaction_count}: earlier messages summarized. "
                    f"Keeping {keep_last} most recent messages.]",
            additional_kwargs={
                "subtype": "compact_boundary",
                "compaction_count": self.compaction_count,
            },
        )

        return [*first, boundary, *recent]
