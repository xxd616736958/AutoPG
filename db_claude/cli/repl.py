"""
REPL interface — Claude Code output style: ⏺ tool calls, ⎿ results, timing.
"""
import os, sys, asyncio, time
from typing import Optional
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.styles import Style
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.completion import Completer, Completion
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from ..utils.config import get_global_config, save_config
from ..context.memory import MemoryManager
from ..context.compact import CompactManager


CLI_STYLE = Style.from_dict({
    "prompt": "bold #00ff87", "input": "#ffffff",
})


class CommandCompleter(Completer):
    def __init__(self, handler): self.handler = handler
    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if text.startswith("/"):
            seen = set()
            for n in sorted(self.handler._commands.keys()):
                if n not in seen and n.startswith(text[1:]):
                    seen.add(n); yield Completion(n, start_position=-len(text) + 1)


class ReplInterface:
    """REPL with Claude Code output format."""

    def __init__(self, query_engine, config=None, command_handler=None):
        self.engine = query_engine
        self.config = config or get_global_config()
        self.cmd = command_handler
        self.console = Console()
        self.should_exit = False
        self.messages_clear = False
        self._compact = CompactManager(model_name=self.config.model)
        # Streaming state
        self._token_count = 0
        self._tool_start_time = 0
        self._thinking_start = 0

    def _get_history_path(self) -> str:
        d = os.path.expanduser("~/.db-claude"); os.makedirs(d, exist_ok=True)
        return os.path.join(d, "history")

    async def run(self):
        self._print_welcome()
        # Wire callbacks
        self.engine.on_stream_token = self._on_token
        self.engine.on_tool_start = self._on_tool_start
        self.engine.on_tool_end = self._on_tool_end

        session = PromptSession(history=FileHistory(self._get_history_path()), style=CLI_STYLE,
                                completer=CommandCompleter(self.cmd) if self.cmd else None)
        while not self.should_exit:
            try:
                user_input = await session.prompt_async(HTML("<prompt>❯ </prompt>"), multiline=False)
                if not user_input.strip(): continue
                if self.cmd and user_input.strip().startswith("/"):
                    ctx = {"config": self.config, "query_engine": self.engine, "memory_manager": MemoryManager(),
                           "messages_clear": False, "should_exit": False, "session_id": self.engine.session_id}
                    result = self.cmd.handle(user_input, ctx)
                    if ctx.get("messages_clear"): self.messages_clear = True
                    if ctx.get("should_exit"): self.should_exit = True
                    if result: self.console.print(Markdown(result))
                    continue

                # Auto-compact check
                cs = self._compact.should_compact(self.engine.mutable_messages)
                if cs["is_at_blocking"]:
                    self.engine.mutable_messages = self._compact.compact_messages(self.engine.mutable_messages, keep_recent=15)

                await self._process(user_input)
            except KeyboardInterrupt:
                sys.stdout.write("\n")
                self.should_exit = True
            except EOFError:
                self.should_exit = True

        self.console.print(f"\n[dim]Session {self.engine.session_id[:8]}... saved.[/dim]")
        save_config(self.config)

    # ── Callbacks ──

    def _on_token(self, token: str):
        self._token_count += 1
        # Tokens are printed by _process event loop — do NOT double-write here

    def _on_tool_start(self, name: str, activity: str):
        self._tool_start_time = time.time()
        # End thinking line if active
        if self._thinking_start > 0:
            sys.stdout.write("\n")
            sys.stdout.flush()
            self._thinking_start = 0

    def _on_tool_end(self, name: str, preview: str):
        pass  # Formatting handled in _process

    # ── Processing ──

    async def _process(self, prompt: str):
        if self.messages_clear:
            self.engine.mutable_messages = []
            self.messages_clear = False

        self._token_count = 0
        self._thinking_start = time.time()
        thinking_shown = False
        streamed = ""

        sys.stdout.write("\n")
        sys.stdout.flush()

        try:
            async for event in self.engine.submit_message(prompt):
                etype = event.get("type", "")

                if etype == "token":
                    tok = event.get("content", "")
                    streamed += tok
                    # Show thinking indicator instead of raw streaming
                    if not thinking_shown:
                        elapsed = time.time() - self._thinking_start
                        if elapsed > 0.3:
                            sys.stdout.write(f"⏺ Thinking…\n")
                            sys.stdout.flush()
                            thinking_shown = True

                elif etype == "tool_start":
                    name = event.get("name", "")
                    # Use pre-formatted call_display from query_loop (already format_call(args))
                    call_display = event.get("call_display", "")
                    if not call_display or call_display == name:
                        # Fallback: build from args
                        args = event.get("args", {})
                        native = None
                        for t in self.engine.tools:
                            if t.name == name or name in (t.aliases or []):
                                native = t; break
                        call_display = native.format_call(args) if native else f"{name}"
                    sys.stdout.write(f"\n⏺ {call_display}\n")
                    sys.stdout.flush()
                    current_tool = name

                elif etype == "tool_end":
                    result_line = event.get("result_preview", "")
                    if not result_line:
                        result_line = "done"
                    sys.stdout.write(f"  ⎿  {result_line}\n")
                    sys.stdout.flush()
                    current_tool = None

                elif etype == "result":
                    # Render the streamed text as formatted Markdown (Claude Code style)
                    sys.stdout.write("\n")
                    sys.stdout.flush()

                    final_text = event.get("result", streamed)
                    if final_text:
                        # Use Rich to render GitHub-flavored Markdown
                        self.console.print(Markdown(final_text))

                    # Timing line
                    duration = event.get("duration_ms", 0) / 1000
                    turns = event.get("num_turns", 0)
                    usage = event.get("usage", {})
                    tok_in = usage.get("input_tokens", 0)
                    tok_out = usage.get("output_tokens", 0)

                    timing_parts = [f"{duration:.1f}s"]
                    if turns > 0: timing_parts.append(f"{turns} turns")
                    if tok_in > 0: timing_parts.append(f"↓ {tok_out:,} tokens")
                    self.console.print(f"[dim]⏺ {', '.join(timing_parts)}[/dim]")

                    errors = event.get("errors", [])
                    for err in errors:
                        self.console.print(f"[red]Error: {err}[/red]")
                    break

        except Exception as e:
            self.console.print(f"\n[red]Error: {str(e)}[/red]")

    def _format_call(self, tool, name: str, activity: str) -> str:
        """Format tool call like: Write(file.py) or Bash(ls -la)"""
        if tool:
            try:
                # Use format_call from tool if available
                return tool.format_call({}) if tool.format_call({}) != tool.name else f"{name}({activity})"
            except:
                pass
        return f"{name}({activity})"

    def _format_result(self, name: str, data: str) -> str:
        """Format result as single line summary, matching Claude Code style."""
        if not data: return "done"
        text = str(data).strip()
        # Try JSON parse for structured results
        if text.startswith("{"):
            try:
                import json
                obj = json.loads(text)
                if "status" in obj: return obj["status"]
                if "count" in obj:
                    return f"{obj['count']} results"
                if "exit_code" in obj:
                    lines = (obj.get("stdout","") + obj.get("stderr","")).strip().split("\n")
                    return lines[0][:100] if lines and lines[0] else f"exit={obj['exit_code']}"
            except: pass
        lines = text.split("\n")
        return lines[0][:120] if lines else text[:120]

    def _print_welcome(self):
        from .. import __version__
        provider = {"deepseek": "DeepSeek", "anthropic": "Anthropic"}.get(self.config.provider, self.config.provider)
        self.console.print(Panel(
            f"[bold]db-claude v{__version__}[/bold]\n"
            f"{provider} · {self.config.model} · {self.config.permission_mode} mode\n"
            "Type [bold]/help[/bold] for commands.",
            border_style="bold blue", title="db-claude",
        ))
