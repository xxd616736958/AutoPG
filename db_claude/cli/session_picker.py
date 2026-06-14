"""
Session picker — Claude Code-style interactive session browser.
"""
from typing import Optional
from datetime import datetime
from prompt_toolkit import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.containers import Window
from prompt_toolkit.styles import Style
from ..utils.session import list_sessions, load_session, resume_messages


PICKER_STYLE = Style.from_dict({
    "header": "bold #ffffff",
    "highlight": "bg:#4444ff #ffffff",
    "dim": "#888888",
    "search-label": "bg:#333333 #ffffff",
    "key-hint": "#666666",
    "current-marker": "#00ff87",
})


def _time_ago(iso_str: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_str)
        diff = datetime.now() - dt
        if diff.days > 30: return f"{diff.days // 30}mo ago"
        if diff.days > 0: return f"{diff.days}d ago"
        hours = diff.seconds // 3600
        if hours > 0: return f"{hours}h ago"
        mins = diff.seconds // 60
        return f"{mins}m ago" if mins > 0 else "now"
    except: return ""


def _fmt_size(b: int) -> str:
    if b > 1024*1024: return f"{b/(1024*1024):.1f}MB"
    if b > 1024: return f"{b/1024:.1f}KB"
    return f"{b}B"


async def pick_session(current_session_id: str = None) -> Optional[str]:
    """Open interactive session picker. Returns session_id or None."""

    sessions = list_sessions(limit=200)
    if not sessions:
        return None

    selected = 0
    search = ""
    preview_id = None
    preview_lines = ["", " Press Space to preview "]

    kb = KeyBindings()

    @kb.add("up")
    def _(e): nonlocal selected; selected = max(0, selected - 1)

    @kb.add("down")
    def _(e):
        nonlocal selected
        f = _filtered()
        selected = min(len(f) - 1, selected + 1) if f else 0

    @kb.add("escape")
    def _(e): nonlocal selected; selected = -1; e.app.exit()

    @kb.add("enter")
    def _(e): e.app.exit()

    @kb.add("space")
    def _(e):
        nonlocal preview_id, preview_lines
        f = _filtered()
        if f and 0 <= selected < len(f):
            preview_id = f[selected]["session_id"]
            data = load_session(preview_id)
            if data:
                msgs = data.get("messages", [])
                lines = [f" Session: {preview_id[:20]}... ", f" Messages: {len(msgs)} ", ""]
                for m in msgs[-10:]:
                    c = str(m.get("content", ""))[:100].replace("\n", " ")
                    lines.append(f"  [{m.get('type','?')}] {c}")
                preview_lines = lines

    @kb.add("c-h")  # Backspace
    def _(e):
        nonlocal search, selected
        search = search[:-1]; selected = 0

    @kb.add("c-a")
    def _(e): nonlocal search; search = ""

    def _filtered():
        if not search: return sessions
        q = search.lower()
        return [s for s in sessions
                if q in s["session_id"].lower()
                or q in s.get("saved_at", "").lower()]

    def _render():
        """Return list of (style, text) tuples for prompt_toolkit rendering."""
        lines = []
        filtered = _filtered()

        # Header
        lines.append(("class:header", "  Resume session\n"))
        lines.append(("", "─" * 60 + "\n"))

        # Search
        sd = search if search else "Type to search…"
        lines.append(("class:search-label", f"  {sd}\n"))
        lines.append(("", "\n"))

        # Sessions
        for i, s in enumerate(filtered[:50]):
            marker = "❯" if i == selected else " "
            style = "class:highlight" if i == selected else ""
            cur = " ← current" if s["session_id"] == current_session_id else ""
            line = (
                f"  {marker} {s['session_id'][:16]}..."
                f"  {s.get('message_count',0)} msgs · {_fmt_size(s.get('size_bytes',0))}"
                f" · {_time_ago(s.get('saved_at',''))}{cur}\n"
            )
            lines.append((style, line))

        # Footer
        lines.append(("", "\n" + "─" * 60 + "\n"))
        lines.append(("class:key-hint",
            "  ↑↓ navigate · Enter select · Esc cancel · Space preview · Type to search\n"))

        # Preview
        if preview_id:
            lines.append(("", "\n" + "─" * 60 + "\n"))
            lines.append(("class:header", "  Preview\n"))
            for pl in preview_lines[:15]:
                lines.append(("class:dim", f"  {pl}\n"))

        return lines

    # Register printable keys
    @kb.add("<any>")
    def _(e):
        nonlocal search, selected
        if e.data and len(e.data) == 1 and e.data.isprintable():
            search += e.data
            selected = 0

    content = FormattedTextControl(
        text=_render,
        focusable=True,
    )
    window = Window(content=content, always_hide_cursor=True)
    layout = Layout(window)
    app = Application(layout=layout, key_bindings=kb, style=PICKER_STYLE, full_screen=False)

    await app.run_async()

    if selected < 0:
        return None
    filtered = _filtered()
    if 0 <= selected < len(filtered):
        return filtered[selected]["session_id"]
    return None
