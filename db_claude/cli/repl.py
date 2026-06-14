"""
REPL interface for db-claude.
Architecturally mirrors Claude Code's REPL (src/screens/REPL.tsx).
Uses prompt_toolkit for a rich terminal interface.
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

from ..utils.config import get_global_config, save_config
from ..context.memory import MemoryManager


# CLI styling
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
    """Auto-complete slash commands."""

    def __init__(self, command_handler):
        self.command_handler = command_handler

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if text.startswith("/"):
            for cmd_name in sorted(self.command_handler._commands.keys()):
                if cmd_name.startswith(text[1:]):
                    yield Completion(cmd_name, start_position=-len(text) + 1)


class ReplInterface:
    """
    Interactive REPL for db-claude.
    Provides a terminal chat interface with streaming responses.

    Usage:
        repl = ReplInterface(query_engine, config)
        await repl.run()
    """

    def __init__(self, query_engine, config=None, command_handler=None):
        self.query_engine = query_engine
        self.config = config or get_global_config()
        self.command_handler = command_handler
        self.console = Console()
        self.should_exit = False
        self.messages_clear = False

    def _get_history_path(self) -> str:
        """Get the path to the command history file."""
        history_dir = os.path.expanduser("~/.db-claude")
        os.makedirs(history_dir, exist_ok=True)
        return os.path.join(history_dir, "history")

    async def run(self):
        """Run the interactive REPL loop."""
        # Print welcome banner
        self._print_welcome()

        # Create prompt session
        session = PromptSession(
            history=FileHistory(self._get_history_path()),
            style=CLI_STYLE,
            completer=CommandCompleter(self.command_handler) if self.command_handler else None,
        )

        # Main loop
        while not self.should_exit:
            try:
                # Get user input
                user_input = await session.prompt_async(
                    HTML("<prompt>❯ </prompt>"),
                    multiline=False,
                )

                if not user_input.strip():
                    continue

                # Handle slash commands
                if self.command_handler and user_input.strip().startswith("/"):
                    context = {
                        "config": self.config,
                        "query_engine": self.query_engine,
                        "memory_manager": MemoryManager(),
                        "messages_clear": False,
                        "should_exit": False,
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

                # Normal message — send to query engine
                await self._process_message(user_input)

            except KeyboardInterrupt:
                self.console.print("\n[yellow]Interrupted. Type /exit to quit.[/yellow]")
            except EOFError:
                self.should_exit = True

        self._print_goodbye()
        save_config(self.config)

    async def _process_message(self, prompt: str):
        """Process a user message through the query engine with streaming display."""
        # Check if we should clear messages
        if self.messages_clear:
            self.query_engine.mutable_messages = []
            self.messages_clear = False

        # Show a spinner while processing
        with Live(
            Panel(Spinner("dots", text=" Thinking..."), border_style="dim blue"),
            console=self.console,
            refresh_per_second=10,
            transient=True,
        ) as live:
            try:
                result = await self.query_engine.submit_message(prompt)
            except Exception as e:
                live.stop()
                self.console.print(f"[error]Error: {str(e)}[/error]")
                return

        # Print the result
        if result.get("type") == "result":
            text = result.get("result", "")
            if text:
                self.console.print(Markdown(text))

            # Show metadata
            duration = result.get("duration_ms", 0) / 1000
            turns = result.get("num_turns", 0)
            stop_reason = result.get("stop_reason", "")
            meta = f"({turns} turns, {duration:.1f}s"
            if stop_reason:
                meta += f", stop={stop_reason}"
            meta += ")"
            self.console.print(f"[dim]{meta}[/dim]")

            # Show errors
            errors = result.get("errors", [])
            for error in errors:
                self.console.print(f"[error]Error: {error}[/error]")

    def _print_welcome(self):
        """Print the welcome banner."""
        from .. import __version__

        provider_display = {
            "deepseek": "DeepSeek",
            "anthropic": "Anthropic",
        }.get(self.config.provider, self.config.provider)

        self.console.print(Panel(
            f"[bold]db-claude v{__version__}[/bold] — Intelligent Coding Agent\n"
            f"Built with LangChain + LangGraph\n\n"
            f"Provider: [bold]{provider_display}[/bold]\n"
            f"Model:    [bold]{self.config.model}[/bold]\n"
            f"Base URL: {self.config.base_url or 'default'}\n"
            f"Perms:    {self.config.permission_mode}\n\n"
            "Type [bold]/help[/bold] for available commands.",
            border_style="bold blue",
            title="Welcome",
        ))

    def _print_goodbye(self):
        """Print the goodbye message."""
        self.console.print("\n[dim]Goodbye![/dim]\n")
