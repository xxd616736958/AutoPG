"""
REPL interface for db-claude with streaming output, tool progress, and session persistence.
Architecturally mirrors Claude Code's REPL (src/screens/REPL.tsx).
"""
import os
import sys
import asyncio
from typing import Optional

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.styles import Style
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.completion import Completer, Completion
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.live import Live
from rich.spinner import Spinner
from rich.text import Text
from rich.table import Table

from ..utils.config import get_global_config, save_config
from ..utils.session import save_session, list_sessions, get_last_session_id
from ..context.memory import MemoryManager
from ..context.compact import CompactManager


CLI_STYLE = Style.from_dict({
    "prompt": "bold #00ff87",
    "input": "#ffffff",
    "thinking": "italic #888888",
    "tool-call": "#ffaa00",
    "tool-result": "#00aaff",
    "error": "#ff0000 bold",
    "info": "#888888",
})


class CommandCompleter(Completer):
    def __init__(self, command_handler):
        self.command_handler = command_handler

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if text.startswith("/"):
            seen = set()
            for cmd_name in sorted(self.command_handler._commands.keys()):
                if cmd_name not in seen and cmd_name.startswith(text[1:]):
                    seen.add(cmd_name)
                    yield Completion(cmd_name, start_position=-len(text) + 1)


class ReplInterface:
    """Interactive REPL with streaming, progress, and session management."""

    def __init__(self, query_engine, config=None, command_handler=None):
        self.query_engine = query_engine
        self.config = config or get_global_config()
        self.command_handler = command_handler
        self.console = Console()
        self.should_exit = False
        self.messages_clear = False
        self.compact_manager = CompactManager(model_name=self.config.model)

    def _get_history_path(self) -> str:
        history_dir = os.path.expanduser("~/.db-claude")
        os.makedirs(history_dir, exist_ok=True)
        return os.path.join(history_dir, "history")

    async def run(self):
        self._print_welcome()

        # Register streaming callbacks on the engine
        self.query_engine.on_stream_token = self._on_token
        self.query_engine.on_tool_start = self._on_tool_start
        self.query_engine.on_tool_end = self._on_tool_end

        session = PromptSession(
            history=FileHistory(self._get_history_path()),
            style=CLI_STYLE,
            completer=CommandCompleter(self.command_handler) if self.command_handler else None,
        )

        while not self.should_exit:
            try:
                user_input = await session.prompt_async(
                    HTML("<prompt>❯ </prompt>"), multiline=False,
                )

                if not user_input.strip():
                    continue

                # Slash commands
                if self.command_handler and user_input.strip().startswith("/"):
                    context = {
                        "config": self.config,
                        "query_engine": self.query_engine,
                        "memory_manager": MemoryManager(),
                        "messages_clear": False,
                        "should_exit": False,
                        "session_id": self.query_engine.session_id,
                    }
                    result = self.command_handler.handle(user_input, context)

                    if context.get("messages_clear"):
                        self.messages_clear = True
                        self.console.print("[info]Conversation cleared.[/info]")

                    if context.get("should_exit"):
                        self.should_exit = True

                    if result:
                        self.console.print(Markdown(result))
                    continue

                # Auto-compact check before processing
                compact_state = self.compact_manager.should_compact(self.query_engine.mutable_messages)
                if compact_state["is_at_blocking"]:
                    self.console.print(
                        f"[yellow]⚡ Context at {compact_state['usage_ratio']:.0%} — compacting...[/yellow]"
                    )
                    self.query_engine.mutable_messages = self.compact_manager.compact_messages(
                        self.query_engine.mutable_messages, keep_recent=15,
                    )
                    new_state = self.compact_manager.should_compact(self.query_engine.mutable_messages)
                    self.console.print(
                        f"[dim]   → {new_state['token_count']:,} tokens "
                        f"({new_state['usage_ratio']:.0%} of {new_state['context_limit']:,})[/dim]"
                    )
                elif compact_state["is_at_warning"]:
                    self.console.print(
                        f"[dim]⚡ Context at {compact_state['usage_ratio']:.0%} "
                        f"({compact_state['token_count']:,}/{compact_state['context_limit']:,} tokens)[/dim]"
                    )

                # Process message with streaming
                await self._process_message_streaming(user_input)

            except KeyboardInterrupt:
                self.console.print("\n[yellow]Interrupted. Type /exit to quit.[/yellow]")
            except EOFError:
                self.should_exit = True

        self._print_goodbye()
        save_config(self.config)

    # ── streaming callbacks ──

    def _on_token(self, token: str):
        """Called for each token from the model. Print inline."""
        self.console.print(token, end="", markup=False, highlight=False)

    def _on_tool_start(self, name: str, activity: str):
        """Called when a tool starts executing."""
        self.console.print(f"\n[yellow]🔧 {activity}[/yellow] ", end="")

    def _on_tool_end(self, name: str, preview: str):
        """Called when a tool finishes."""
        self.console.print("[dim]✓[/dim]")

    # ── streaming message processing ──

    async def _process_message_streaming(self, prompt: str):
        """Process a message with full streaming display."""
        if self.messages_clear:
            self.query_engine.mutable_messages = []
            self.messages_clear = False

        self.console.print()  # Newline before response

        try:
            async for event in self.query_engine.submit_message(prompt):
                etype = event.get("type", "")

                if etype == "token":
                    # Already printed via callback
                    pass

                elif etype == "tool_start":
                    name = event.get("name", "")
                    activity = event.get("activity", name)
                    self.console.print(f"\n[yellow]🔧 {activity}[/yellow] ", end="")

                elif etype == "tool_end":
                    self.console.print("[dim]✓[/dim]")
                    preview = event.get("result_preview", "")
                    if preview and self.config.verbose:
                        self.console.print(f"[dim]   {preview[:120]}[/dim]")

                elif etype == "state_update":
                    pass  # Internal state tracking

                elif etype == "result":
                    self.console.print()  # Final newline
                    text = event.get("result", "")
                    if text:
                        self.console.print(Markdown(text))

                    # Show metadata
                    duration = event.get("duration_ms", 0) / 1000
                    turns = event.get("num_turns", 0)
                    usage = event.get("usage", {})
                    meta_parts = [f"{turns} turns", f"{duration:.1f}s"]
                    if usage:
                        tok_in = usage.get("input_tokens", 0)
                        tok_out = usage.get("output_tokens", 0)
                        meta_parts.append(f"{tok_in:,}+{tok_out:,} tokens")
                    self.console.print(f"[dim]({' | '.join(meta_parts)})[/dim]")

                    errors = event.get("errors", [])
                    for err in errors:
                        self.console.print(f"[error]Error: {err}[/error]")

                    break

        except Exception as e:
            self.console.print(f"\n[error]Error: {str(e)}[/error]")

    # ── welcome / goodbye ──

    def _print_welcome(self):
        from .. import __version__

        provider_display = {"deepseek": "DeepSeek", "anthropic": "Anthropic"}.get(
            self.config.provider, self.config.provider
        )
        sid = self.query_engine.session_id[:8]

        self.console.print(Panel(
            f"[bold]db-claude v{__version__}[/bold] — Intelligent Coding Agent\n"
            f"Built with LangChain + LangGraph\n\n"
            f"Provider: [bold]{provider_display}[/bold]\n"
            f"Model:    [bold]{self.config.model}[/bold]\n"
            f"Session:  {sid}...\n"
            f"Perms:    {self.config.permission_mode}\n\n"
            "Type [bold]/help[/bold] for commands. [bold]/session[/bold] to manage sessions.",
            border_style="bold blue", title="Welcome",
        ))

    def _print_goodbye(self):
        sid = self.query_engine.session_id[:8]
        self.console.print(f"\n[dim]Session {sid}... saved. Goodbye![/dim]\n")
