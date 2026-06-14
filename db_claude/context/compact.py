"""
Context compaction for db-claude with token counting.
Architecturally mirrors Claude Code's compaction system (src/services/compact/).
Works offline — falls back to character-based estimation when tiktoken is unavailable.
"""
import re
from typing import Optional
from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage, AIMessage


class CompactManager:
    """
    Manages context compaction with real token counting.
    Uses tiktoken when available, falls back to character-based estimation.
    """

    AUTO_COMPACT_WARNING = 0.70
    AUTO_COMPACT_TRIGGER = 0.80
    AUTO_COMPACT_BLOCKING = 0.95

    CONTEXT_LIMITS = {
        "deepseek-v4-flash": 131072,
        "deepseek-v4-pro": 131072,
        "deepseek-chat": 65536,
        "deepseek-reasoner": 65536,
        "claude-opus-4-6": 200000,
        "claude-sonnet-4-6": 200000,
        "claude-haiku-4-5-20251001": 200000,
    }
    DEFAULT_LIMIT = 131072

    def __init__(self, model_name: str = "claude-sonnet-4-6"):
        self.model_name = model_name
        self.context_limit = self.CONTEXT_LIMITS.get(model_name, self.DEFAULT_LIMIT)
        self.compaction_count = 0
        self._encoder = None
        self._init_encoder()

    def _init_encoder(self):
        """Try to load tiktoken encoder; fall back to regex-based tokenizer."""
        try:
            import tiktoken
            self._encoder = tiktoken.get_encoding("cl100k_base")
        except Exception:
            self._encoder = None

    def count_tokens(self, text: str) -> int:
        """Count tokens — tiktoken if available, else regex-based estimation."""
        if self._encoder:
            try:
                return len(self._encoder.encode(text))
            except Exception:
                pass
        # Fallback: regex-based GPT-like BPE tokenization
        # Matches contractions, words, numbers, punctuation, whitespace
        pattern = re.compile(
            r"""'s|'t|'re|'ve|'m|'ll|'d| ?[A-Za-z]+| ?[0-9]+| ?[^\s\w]+|\s+""",
            re.VERBOSE,
        )
        return max(1, len(pattern.findall(text)))

    def estimate_total_tokens(self, messages: list[BaseMessage]) -> int:
        """Estimate total tokens for a list of messages."""
        total = 0
        for msg in messages:
            # Message role overhead (~4 tokens)
            total += 4

            # Content tokens
            content = msg.content if hasattr(msg, "content") else str(msg)
            if isinstance(content, str):
                total += self.count_tokens(content)
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        total += self.count_tokens(block.get("text", str(block)))
                    else:
                        total += self.count_tokens(str(block))

            # Tool calls overhead
            tool_calls = getattr(msg, "tool_calls", None) or []
            for tc in tool_calls:
                tc_str = str(tc.get("args", {}))
                total += self.count_tokens(tc_str) + 8  # function call overhead

        return total

    def should_compact(self, messages: list[BaseMessage]) -> dict:
        """Check if compaction is needed."""
        token_count = self.estimate_total_tokens(messages)
        ratio = token_count / self.context_limit if self.context_limit > 0 else 0

        return {
            "token_count": token_count,
            "context_limit": self.context_limit,
            "usage_ratio": ratio,
            "is_at_warning": ratio >= self.AUTO_COMPACT_WARNING,
            "should_compact": ratio >= self.AUTO_COMPACT_TRIGGER,
            "is_at_blocking": ratio >= self.AUTO_COMPACT_BLOCKING,
        }

    def compact_messages(
        self,
        messages: list[BaseMessage],
        keep_recent: int = 20,
        keep_system: bool = True,
    ) -> list[BaseMessage]:
        """
        Compact conversation history.
        Strategy:
        1. Keep the first system message
        2. Keep the most recent N messages
        3. Replace middle messages with a compact boundary marker
        4. Generate a summary of removed content
        """
        if not messages or len(messages) <= keep_recent:
            return messages

        self.compaction_count += 1

        # Separate system messages from conversation
        system_msgs = []
        conversation = []
        for msg in messages:
            if isinstance(msg, SystemMessage):
                system_msgs.append(msg)
            else:
                conversation.append(msg)

        # If the conversation is already small, don't compact
        if len(conversation) <= keep_recent:
            return messages

        # Calculate how many to remove
        remove_count = len(conversation) - keep_recent
        removed = conversation[:remove_count]
        kept = conversation[remove_count:]

        # Build summary of removed content
        summary_parts = []
        for msg in removed:
            if isinstance(msg, HumanMessage):
                content = str(msg.content)[:200]
                summary_parts.append(f"[User]: {content}")
            elif isinstance(msg, AIMessage):
                content = str(msg.content)[:200]
                if content:
                    summary_parts.append(f"[Assistant]: {content}")
                tool_calls = getattr(msg, "tool_calls", None) or []
                for tc in tool_calls:
                    summary_parts.append(f"  → called {tc.get('name', 'unknown')}")

        summary_text = (
            f"## Context Compaction #{self.compaction_count}\n\n"
            f"Earlier conversation ({remove_count} messages) has been summarized "
            f"to stay within the {self.context_limit:,}-token context window.\n\n"
            f"### Summary of removed content:\n"
            + "\n".join(f"- {p}" for p in summary_parts[:30])
            + ("\n- ... (more messages omitted)" if len(summary_parts) > 30 else "")
            + f"\n\n### Preserved ({len(kept)} most recent messages):\n"
        )

        boundary = SystemMessage(
            content=summary_text,
            additional_kwargs={
                "subtype": "compact_boundary",
                "compaction_count": self.compaction_count,
                "removed_count": remove_count,
                "kept_count": len(kept),
            },
        )

        # Assemble: system messages + boundary + recent conversation
        result = system_msgs + [boundary] + kept

        # Log compaction stats
        old_tokens = self.estimate_total_tokens(messages)
        new_tokens = self.estimate_total_tokens(result)
        print(f"  [dim]⚡ Compacted: {old_tokens:,} → {new_tokens:,} tokens "
              f"({remove_count} messages summarized)[/dim]")

        return result
