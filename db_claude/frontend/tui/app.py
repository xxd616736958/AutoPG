"""
Textual TUI — Claude Code-style terminal UI for db-claude.
Replaces prompt_toolkit + sys.stdout with unified Textual App.
"""
import os, sys, asyncio
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Header, Footer, Input, RichLog, Static
from textual.reactive import reactive
from textual.css.query import NoMatches
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

# Add project root for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))


class ClaudeApp(App):
    """Textual TUI matching Claude Code's terminal experience."""

    CSS = """
    Header { dock: top; height: 1; }
    Footer { dock: bottom; height: 1; }
    #message-list { height: 1fr; overflow-y: auto; }
    #input-area { height: 3; dock: bottom; padding: 0 1; }
    #prompt { width: 100%; }
    .token-text { color: #cccccc; }
    .tool-call { color: #ffaa00; }
    .tool-result { color: #888888; }
    .thinking { color: #666666; italic: true; }
    .meta-line { color: #666666; }
    """

    session_id = reactive("")

    def __init__(self, engine=None):
        super().__init__()
        self._engine = engine
        self._streaming_task = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield RichLog(id="message-list", highlight=True, markup=True, wrap=True)
        yield Container(
            Input(id="prompt", placeholder="Type your message..."),
            id="input-area",
        )
        yield Footer()

    def on_mount(self):
        """Initialize engine and show welcome."""
        self.session_id = self._engine.session_id if self._engine else ""
        self._log_message(f"[bold blue]db-claude v1.0[/bold blue] — {self._engine.model_name}")
        self.query_one("#prompt").focus()

    async def on_input_submitted(self, event: Input.Submitted):
        """User pressed Enter — send message to agent."""
        prompt = event.value.strip()
        if not prompt:
            return

        # Clear input
        self.query_one("#prompt").value = ""

        # Show user message
        self._log_message(f"\n[bold]❯ {prompt[:100]}[/bold]")

        # Process
        ml = self.query_one("#message-list")
        ml.write(Text("⏺ Thinking…", style="thinking"))

        self._streaming_task = asyncio.create_task(self._process_message(prompt))

    async def _process_message(self, prompt: str):
        """Run agent and stream events to TUI."""
        try:
            accumulated = ""
            tokens_since_newline = 0
            async for event in self._engine.submit_message(prompt):
                etype = event.get("type", "")

                if etype == "token":
                    token = event["content"]
                    accumulated += token
                    tokens_since_newline += len(token)
                    # Batch writes to avoid excessive updates
                    if tokens_since_newline > 80 or "\n" in token:
                        ml = self.query_one("#message-list")
                        ml.write(Text(accumulated, style="token-text"))
                        accumulated = ""
                        tokens_since_newline = 0
                        await asyncio.sleep(0)

                elif etype == "tool_start":
                    ml = self.query_one("#message-list")
                    name = event.get("name", "")
                    display = event.get("call_display", name)
                    ml.write(Text(f"  ⏺ {display}", style="tool-call"))

                elif etype == "tool_end":
                    ml = self.query_one("#message-list")
                    result = event.get("result_preview", "done")
                    ml.write(Text(f"    ⎿  {result}", style="tool-result"))

                elif etype == "result":
                    # Flush remaining accumulated tokens
                    if accumulated:
                        ml = self.query_one("#message-list")
                        ml.write(Markdown(accumulated))
                        accumulated = ""
                    # Show timing
                    duration = event.get("duration_ms", 0) / 1000
                    turns = event.get("num_turns", 0)
                    usage = event.get("usage", {})
                    tokens_in = usage.get("input_tokens", 0)
                    tokens_out = usage.get("output_tokens", 0)
                    meta = f"  ⏺ {duration:.1f}s · {turns} turns"
                    if tokens_out > 0:
                        meta += f" · ↓ {tokens_out:,} tokens"
                    ml = self.query_one("#message-list")
                    ml.write(Text(meta, style="meta-line"))

        except Exception as e:
            ml = self.query_one("#message-list")
            ml.write(Text(f"\nError: {str(e)}", style="bold red"))
        finally:
            self.query_one("#prompt").focus()

    def _log_message(self, text: str):
        try:
            self.query_one("#message-list").write(text)
        except NoMatches:
            pass


def run_tui(engine):
    """Entry point for Textual TUI."""
    app = ClaudeApp(engine=engine)
    app.run()


if __name__ == "__main__":
    import asyncio as _asyncio
    from db_claude.tools import ALL_TOOLS
    from db_claude.agent.query_engine import QueryEngine
    engine = QueryEngine(tools=ALL_TOOLS, model_name="deepseek-v4-flash",
                         provider="deepseek", cwd=os.getcwd())
    run_tui(engine)
