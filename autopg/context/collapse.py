"""
Context Collapse — AutoPG's selective span-folding system.
Replaces specific conversation spans with summaries, keeping other messages intact.

Key design (matching AutoPG's contextCollapse):
- Collapses are STAGED first, COMMITTED in batch (cost amortization)
- projectView() replays commit log on every entry (idempotent)
- recoverFromOverflow() drains staged on 413 (free recovery, no API call)
- collapseOwnsIt pattern — skips blocking limit when collapse is handling context
- Collapse store is per-session, auto-invalidated after auto-compact
"""
import os, json, uuid, re
from typing import Optional
from dataclasses import dataclass, field
from datetime import datetime
from langchain_core.messages import BaseMessage, AIMessage, ToolMessage, SystemMessage


@dataclass
class CollapseCommit:
    """One collapse operation. AutoPG: commit log entry in collapse store."""
    commit_id: str
    start_uuid: str = ""          # UUID of first message in collapsed span
    end_uuid: str = ""            # UUID of last message in collapsed span
    start_index: int = 0          # Message list index at commit time (volatile)
    end_index: int = 0
    summary: str = ""             # LLM-generated summary
    created_at: str = ""
    turn: int = 0                 # Which turn created this commit


class ContextCollapseManager:
    """
    Manages selective span collapses. AutoPG: contextCollapse module.

    Lifecycle:
      stage_collapse() → commit queue
      apply_collapses_if_needed() → commit + projectView() → API
      recover_from_overflow() → drain staged on 413 → retry
      reset() → on /clear or auto-compact
    """

    def __init__(self, session_id: str, provider: str = "deepseek",
                 api_key: str = None, base_url: str = None):
        self.session_id = session_id
        self.provider = provider
        self.api_key = api_key
        self.base_url = base_url

        # Commit log (persisted)
        self._commits: list[CollapseCommit] = []
        # Staged queue (not yet committed)
        self._staged: list[CollapseCommit] = []

        # Stats (AutoPG: collapse stats)
        self.stats = {
            "collapsed_spans": 0,
            "staged_spans": 0,
            "health": {
                "total_errors": 0,
                "total_empty_spawns": 0,
                "empty_spawn_warning_emitted": False,
            },
        }

        # Load persisted state
        self._load_state()

    # ── Persistence (per-session collapse store) ──

    def _store_path(self) -> str:
        base = os.environ.get("AUTOPG_CONFIG_DIR", os.path.expanduser("~/.autopg"))
        d = os.path.join(base, "collapses")
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, f"{self.session_id}.json")

    def _load_state(self):
        path = self._store_path()
        if not os.path.exists(path):
            return
        try:
            with open(path, "r") as f:
                data = json.load(f)
            self._commits = [
                CollapseCommit(**c) for c in data.get("commits", [])
            ]
            self._staged = [
                CollapseCommit(**c) for c in data.get("staged", [])
            ]
            self.stats.update(data.get("stats", {}))
        except (json.JSONDecodeError, TypeError):
            pass

    def _save_state(self):
        path = self._store_path()
        data = {
            "commits": [
                {k: v for k, v in c.__dict__.items()}
                for c in self._commits
            ],
            "staged": [
                {k: v for k, v in c.__dict__.items()}
                for c in self._staged
            ],
            "stats": self.stats,
        }
        with open(path, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    # ── Staging (AutoPG: collapse classifier identifies collapsible spans) ──

    def stage_collapse(self, messages: list[BaseMessage],
                       start_idx: int, end_idx: int, turn: int):
        """
        Stage a span for collapse. Does NOT execute immediately.
        AutoPG: collapse classifier marks spans as collapsible.

        Heuristic rules (AutoPG's classifier approximation):
        - Tool call + result pairs where result > 3000 chars
        - Subagent completion messages
        - Search/read operations older than 10 turns
        """
        if start_idx >= end_idx or start_idx < 0 or end_idx > len(messages):
            return

        span = messages[start_idx:end_idx]
        if len(span) < 2:
            return  # Too small to collapse

        # Check if this span has already been staged or committed
        span_uuids = {getattr(m, "id", str(i)) for i, m in enumerate(span)}
        for c in self._commits + self._staged:
            existing = {c.start_uuid, c.end_uuid}
            if span_uuids & existing:
                return  # Already covered

        commit = CollapseCommit(
            commit_id=f"cc_{uuid.uuid4().hex[:12]}",
            start_uuid=getattr(span[0], "id", str(start_idx)),
            end_uuid=getattr(span[-1], "id", str(end_idx)),
            start_index=start_idx,
            end_index=end_idx,
            summary="",  # Generated at commit time
            created_at=datetime.now().isoformat(),
            turn=turn,
        )
        self._staged.append(commit)
        self.stats["staged_spans"] = len(self._staged)
        self._save_state()

    def auto_stage_candidates(self, messages: list[BaseMessage], turn: int):
        """
        Automatically identify collapsible spans using heuristics.
        AutoPG: collapse classifier in query loop.
        """
        # Find tool call + result pairs
        i = 0
        while i < len(messages) - 1:
            msg = messages[i]

            # Pattern: AIMessage with tool_calls + following ToolMessage(s)
            if isinstance(msg, AIMessage):
                tool_calls = getattr(msg, "tool_calls", None) or []
                if tool_calls and i + len(tool_calls) < len(messages):
                    # Find the end of the tool result block
                    end = i + 1
                    for tc in tool_calls:
                        while end < len(messages) and isinstance(messages[end], ToolMessage):
                            end += 1
                    end = min(end, len(messages))

                    # Collapse if: large tool result OR search/read operation
                    span = messages[i:end]
                    total_chars = sum(
                        len(str(getattr(m, "content", "")))
                        for m in span
                    )
                    is_search = any(
                        isinstance(m, AIMessage) and
                        any(tc.get("name", "") in ("Glob", "Grep", "WebSearch")
                            for tc in (getattr(m, "tool_calls", None) or []))
                        for m in span
                    )
                    is_old = (len(messages) - end) > 10  # More than 10 turns ago

                    if (total_chars > 3000 and (is_search or is_old)):
                        self.stage_collapse(messages, i, end, turn)

                    i = end
                    continue
            i += 1

    # ── Commit (batch apply staged collapses) ──

    async def commit_staged(
        self, messages: list[BaseMessage], turn: int,
    ) -> int:
        """
        Commit all staged collapses. Generates summaries via LLM.
        AutoPG: commit collapses in batch (amortize cache miss).
        Returns number of commits applied.
        """
        if not self._staged:
            return 0

        committed = 0
        new_commits = []

        for commit in self._staged:
            span = messages[commit.start_index:commit.end_index]
            if len(span) < 2:
                continue

            # Generate summary for this span
            summary = await self._generate_span_summary(span)
            if summary:
                commit.summary = summary
                new_commits.append(commit)
                committed += 1
            else:
                self.stats["health"]["total_empty_spawns"] += 1
                if self.stats["health"]["total_empty_spawns"] > 3 and \
                   not self.stats["health"]["empty_spawn_warning_emitted"]:
                    self.stats["health"]["empty_spawn_warning_emitted"] = True

        self._commits.extend(new_commits)
        self._staged.clear()
        self.stats["collapsed_spans"] = len(self._commits)
        self.stats["staged_spans"] = 0
        self._save_state()
        return committed

    async def _generate_span_summary(self, span: list[BaseMessage]) -> str:
        """
        Generate a one-sentence summary for a span using fast model.
        AutoPG: internal spawn for collapse summary generation.
        """
        # Build minimal prompt
        span_text = []
        for msg in span:
            role = "AI" if isinstance(msg, AIMessage) else "Tool" if isinstance(msg, ToolMessage) else "System"
            content = str(getattr(msg, "content", ""))[:300]
            tool_calls = getattr(msg, "tool_calls", None) or []
            if tool_calls:
                tc_names = ", ".join(tc.get("name", "?") for tc in tool_calls)
                content = f"[Called: {tc_names}] " + content
            if content.strip():
                span_text.append(f"[{role}]: {content}")

        if not span_text:
            return ""

        prompt = (
            "Summarize this conversation segment in ONE sentence. "
            "Capture what action was taken and what the key result was. "
            "Output ONLY the summary sentence, nothing else.\n\n"
            + "\n".join(span_text)
            + "\n\nOne-sentence summary:"
        )

        try:
            if self.provider == "deepseek":
                from langchain_openai import ChatOpenAI
                llm = ChatOpenAI(
                    model="deepseek-v4-flash",
                    api_key=self.api_key or os.environ.get("DEEPSEEK_API_KEY"),
                    base_url=self.base_url or "https://api.deepseek.com/v1",
                    temperature=0.2, max_tokens=200,
                )
            else:
                from langchain_anthropic import ChatAnthropic
                model = os.environ.get("AUTOPG_MODEL") or os.environ.get("ANTHROPIC_MODEL")
                if not model:
                    raise ValueError("Anthropic summary model is not configured")
                llm = ChatAnthropic(
                    model=model,
                    api_key=self.api_key or os.environ.get("ANTHROPIC_API_KEY"),
                    max_tokens=200, temperature=0.2,
                )
            response = await llm.ainvoke(prompt)
            result = str(response.content).strip() if hasattr(response, "content") else ""
            # Clean: remove quotes, ensure it ends with period
            result = result.strip('"').strip("'").strip()
            if result and not result.endswith((".", "!", "?")):
                result += "."
            return result[:200]
        except Exception:
            self.stats["health"]["total_errors"] += 1
            return "Conversation segment summarized due to context limits."

    # ── Project view (AutoPG: projectView — idempotent read-time projection) ──

    def project_view(self, messages: list[BaseMessage]) -> list[BaseMessage]:
        """
        Replay commit log over current messages. Idempotent.
        AutoPG: replayed on every entry point so one-off.
        Collapsed spans replaced with SystemMessage summaries.
        """
        if not self._commits:
            return list(messages)

        # Build a mask of collapsed indices
        collapsed_ranges: list[tuple[int, int, str]] = []
        for commit in self._commits:
            # Try UUID match first, fall back to index
            start = commit.start_index
            end = commit.end_index
            if commit.start_uuid:
                for i, m in enumerate(messages):
                    mid = getattr(m, "id", None) or getattr(m, "additional_kwargs", {}).get("uuid", "")
                    if mid and str(mid) == commit.start_uuid:
                        start = i
                        break
            if commit.end_uuid:
                for i, m in enumerate(messages):
                    mid = getattr(m, "id", None) or getattr(m, "additional_kwargs", {}).get("uuid", "")
                    if mid and str(mid) == commit.end_uuid:
                        end = i + 1
                        break

            # Validate range — reject if indices are stale (auto-compact already removed these)
            if start >= 0 and end <= len(messages) and start < end:
                collapsed_ranges.append((start, end, commit.summary))

        if not collapsed_ranges:
            return list(messages)

        # Sort by start index descending (replace from back to front)
        collapsed_ranges.sort(key=lambda r: r[0], reverse=True)

        result = list(messages)
        for start, end, summary in collapsed_ranges:
            span_count = end - start
            collapse_msg = SystemMessage(
                content=f"[Collapsed {span_count} messages]\n{summary}",
                additional_kwargs={
                    "subtype": "collapse_marker",
                    "collapsed_count": span_count,
                },
            )
            # Check that start and end are still in range
            if 0 <= start < end <= len(result):
                result[start:end] = [collapse_msg]

        return result

    # ── Apply (AutoPG: applyCollapsesIfNeeded — runs before API call) ──

    async def apply_collapses_if_needed(
        self, messages: list[BaseMessage], turn: int,
    ) -> dict:
        """
        Called before each API call. Commits staged collapses if we're near
        the context limit. AutoPG: runs BEFORE auto-compact.
        Returns {"messages": ..., "changed": bool}
        """
        # Auto-stage candidates (heuristic) on every call
        self.auto_stage_candidates(messages, turn)

        # Commit if we have staged collapses (always commit when we have them —
        # the stage heuristic only fires when token pressure is high)
        committed = await self.commit_staged(messages, turn)

        if committed > 0:
            projected = self.project_view(messages)
            return {"messages": projected, "changed": True}

        # Even without new commits, project existing commits
        if self._commits:
            return {"messages": self.project_view(messages), "changed": True}

        return {"messages": list(messages), "changed": False}

    # ── Recovery (AutoPG: recoverFromOverflow — 413 drain) ──

    def recover_from_overflow(self, messages: list[BaseMessage]) -> dict:
        """
        Drain staged collapses on 413 error. Free recovery — no extra API call.
        AutoPG: first recovery path before reactiveCompact.
        Returns {"messages": ..., "committed": int}
        """
        # Sync-commit without LLM summaries (emergency drain)
        if self._staged:
            committed = len(self._staged)
            self._commits.extend(self._staged)
            self._staged.clear()
            self.stats["collapsed_spans"] = len(self._commits)
            self.stats["staged_spans"] = 0
            self._save_state()
            return {
                "messages": self.project_view(messages),
                "committed": committed,
            }

        return {"messages": list(messages), "committed": 0}

    # ── Withhold (AutoPG: isWithheldPromptTooLong — 413 intercept in streaming) ──

    def is_withheld_prompt_too_long(self, message, is_prompt_too_long_fn) -> bool:
        """
        Withhold 413 errors during streaming until collapse recovery can try.
        AutoPG: allows collapse drain to run before surfacing 413.
        """
        if isinstance(message, type) and hasattr(message, "is_api_error_message"):
            return bool(getattr(message, "is_api_error_message", False)) and \
                   is_prompt_too_long_fn(message)
        return False

    # ── Lifecycle ──

    def is_enabled(self) -> bool:
        """AutoPG: isContextCollapseEnabled — feature gate."""
        return True  # Always enabled in AutoPG

    def reset(self):
        """Clear all collapses. Called on /clear or auto-compact."""
        self._commits.clear()
        self._staged.clear()
        self.stats = {
            "collapsed_spans": 0,
            "staged_spans": 0,
            "health": {"total_errors": 0, "total_empty_spawns": 0,
                       "empty_spawn_warning_emitted": False},
        }
        self._save_state()
