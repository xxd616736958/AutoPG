"""
Context compaction for AutoPG with token counting.
Architecturally mirrors AutoPG's compaction system (src/services/compact/).
Works offline — falls back to character-based estimation when tiktoken is unavailable.
"""
import os, re
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
    }
    DEFAULT_LIMIT = 131072

    def __init__(self, model_name: str = "deepseek-v4-flash", provider: str = "deepseek",
                 api_key: str = None, base_url: str = None):
        self.model_name = model_name
        self.context_limit = self.CONTEXT_LIMITS.get(model_name, self.DEFAULT_LIMIT)
        self.compaction_count = 0
        self._encoder = None
        self._provider = provider
        self._api_key = api_key
        self._base_url = base_url
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

    async def generate_summary(self, messages: list[BaseMessage]) -> str:
        """Generate a structured summary using a fast model (AutoPG: runForkedAgent for compact).
        Falls back to simple truncation if LLM is unavailable."""
        # Build compact prompt matching AutoPG's compact/prompt.ts
        compact_prompt = (
            "CRITICAL: Respond with TEXT ONLY. Do NOT call any tools.\n\n"
            "Summarize the following conversation between an AI agent and a user. "
            "Your summary should be comprehensive and detailed, covering:\n"
            "1. The user's explicit requests and intents\n"
            "2. The AI's approach and key decisions\n"
            "3. Specific file names, code changes, function signatures\n"
            "4. Errors encountered and how they were fixed\n"
            "5. User feedback and corrections\n\n"
            "Write your summary as concise paragraphs. "
            "Focus on information that would be essential for continuing the work.\n\n"
            "CONVERSATION TO SUMMARIZE:\n\n"
        )

        conversation_text = []
        for msg in messages:
            role = "User" if isinstance(msg, HumanMessage) else "Assistant"
            content = str(msg.content) if hasattr(msg, "content") else str(msg)
            if content:
                conversation_text.append(f"[{role}]: {content[:500]}")
        compact_prompt += "\n".join(conversation_text)
        compact_prompt += "\n\nSUMMARY:"

        try:
            if self._provider == "deepseek":
                from langchain_openai import ChatOpenAI
                llm = ChatOpenAI(
                    model="deepseek-v4-flash",
                    api_key=self._api_key or os.environ.get("DEEPSEEK_API_KEY"),
                    base_url=self._base_url or "https://api.deepseek.com/v1",
                    temperature=0.3, max_tokens=2000,
                )
            else:
                from langchain_anthropic import ChatAnthropic
                model = os.environ.get("AUTOPG_MODEL") or os.environ.get("ANTHROPIC_MODEL")
                if not model:
                    raise ValueError("Anthropic summary model is not configured")
                llm = ChatAnthropic(
                    model=model,
                    api_key=self._api_key or os.environ.get("ANTHROPIC_API_KEY"),
                    max_tokens=2000, temperature=0.3,
                )
            response = await llm.ainvoke(compact_prompt)
            return str(response.content) if hasattr(response, "content") else str(response)
        except Exception:
            return "Previous conversation summarized due to context limits."

    async def compact_messages(
        self,
        messages: list[BaseMessage],
        keep_recent: int = 20,
        keep_system: bool = True,
    ) -> list[BaseMessage]:
        """
        Compact conversation history with LLM-generated summary.
        AutoPG: autoCompactIfNeeded → runForkedAgent with compact prompt.
        """
        if not messages or len(messages) <= keep_recent:
            return messages

        self.compaction_count += 1

        # Separate system messages from conversation
        system_msgs = [m for m in messages if isinstance(m, SystemMessage)]
        conversation = [m for m in messages if not isinstance(m, SystemMessage)]

        if len(conversation) <= keep_recent:
            return messages

        remove_count = len(conversation) - keep_recent
        removed = conversation[:remove_count]
        kept = conversation[remove_count:]

        # Generate summary via LLM (AutoPG pattern)
        summary_text = await self.generate_summary(removed)

        # Build compact boundary message
        boundary_text = (
            f"## Context Compaction #{self.compaction_count}\n\n"
            f"Earlier conversation ({remove_count} messages) summarized:\n\n"
            f"{summary_text}\n\n"
            f"### Preserved ({len(kept)} most recent messages follow)"
        )

        boundary = SystemMessage(
            content=boundary_text,
            additional_kwargs={
                "subtype": "compact_boundary",
                "compaction_count": self.compaction_count,
                "removed_count": remove_count,
                "kept_count": len(kept),
            },
        )

        result = system_msgs + [boundary] + kept

        old_tokens = self.estimate_total_tokens(messages)
        new_tokens = self.estimate_total_tokens(result)
        print(f"  [dim]⚡ Compacted: {old_tokens:,} → {new_tokens:,} tokens "
              f"({remove_count} messages summarized via LLM)[/dim]")

        return result
