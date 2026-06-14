"""
Session picker — fully matching Claude Code's /resume UI.
"""
from typing import Optional
from datetime import datetime
from prompt_toolkit import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.containers import Window
from prompt_toolkit.styles import Style
from ..utils.session import list_sessions, load_session


PICKER_STYLE = Style.from_dict({
    "header": "bold",
    "selected": "bold",
    "dim": "#888888",
    "search-box": "#ffffff",
    "search-placeholder": "#666666",
    "key-hint": "#666666",
    "border": "#444444",
})


def _time_ago(iso_str: str) -> str:
    """Natural relative time — matching Claude Code format."""
    try:
        dt = datetime.fromisoformat(iso_str)
        diff = datetime.now() - dt
        if diff.days > 365: return f"{diff.days // 365} years ago"
        if diff.days > 30: return f"{diff.days // 30} months ago"
        if diff.days == 1: return "yesterday"
        if diff.days > 1: return f"{diff.days} days ago"
        hours = diff.seconds // 3600
        if hours == 1: return "1 hour ago"
        if hours > 1: return f"{hours} hours ago"
        mins = diff.seconds // 60
        if mins <= 1: return "just now"
        if mins < 60: return f"{mins} minutes ago"
        return "just now"
    except:
        return ""


def _fmt_size(b: int) -> str:
    """Human-readable size — matching Claude Code."""
    if b > 1024*1024: return f"{b/(1024*1024):.1f}MB"
    if b > 1024: return f"{b/1024:.1f}KB"
    return f"{b}B"


async def pick_session(current_session_id: str = None) -> Optional[str]:
    """Interactive session picker matching Claude Code's /resume UI."""

    sessions = list_sessions(limit=200)
    if not sessions:
        return None

    selected = 0
    search = ""

    kb = KeyBindings()

    @kb.add("up")
    def _(e): nonlocal selected; selected = max(0, selected - 1)

    @kb.add("down")
    def _(e):
        nonlocal selected
        f = _filtered()
        if f: selected = min(len(f) - 1, selected + 1)

    @kb.add("escape")
    def _(e): nonlocal selected; selected = -1; e.app.exit()

    @kb.add("enter")
    def _(e): e.app.exit()

    @kb.add("space")
    def _(e):
        """Preview — handled post-selection if needed."""
        pass

    @kb.add("c-h")
    def _(e): nonlocal search, selected; search = search[:-1]; selected = 0

    @kb.add("c-a")
    def _(e): nonlocal search; search = ""

    def _filtered():
        if not search: return sessions
        q = search.lower()
        return [s for s in sessions
                if q in s["session_id"].lower()
                or q in s.get("title", "").lower()]

    def _render():
        """Return [(style, text), ...] for prompt_toolkit."""
        lines = []
        filtered = _filtered()
        W = 80  # Width

        # ── Header ──
        lines.append(("", "\n"))
        lines.append(("class:header", "  Resume session\n"))
        lines.append(("class:border", "  " + "─" * (W - 4) + "\n"))

        # ── Search box with border ──
        lines.append(("class:border", "  ╭" + "─" * (W - 6) + "╮\n"))
        sd = search if search else "⌕ Search…"
        search_style = "class:search-box" if search else "class:search-placeholder"
        lines.append((search_style, f"  │ {sd}" + " " * (W - 7 - len(sd)) + "│\n"))
        lines.append(("class:border", "  ╰" + "─" * (W - 6) + "╯\n"))
        lines.append(("", "\n"))

        # ── Session list ──
        has_any = False
        for i, s in enumerate(filtered[:50]):
            has_any = True
            sid = s["session_id"]
            title = s.get("title", "")
            display_name = title if title else f"{sid[:16]}..."

            # Selected line with ❯
            if i == selected:
                prefix = "❯"
                style = "class:selected"
            else:
                prefix = " "
                style = ""

            msg_count = s.get("message_count", 0)
            size = _fmt_size(s.get("size_bytes", 0))
            ago = _time_ago(s.get("saved_at", ""))
            branch = s.get("branch", "")

            # First line: title
            cur = " · ← current" if sid == current_session_id else ""
            lines.append((style, f"  {prefix} {display_name}{cur}\n"))

            # Second line: metadata
            meta_parts = [ago]
            if branch: meta_parts.append(branch)
            meta_parts.append(size)
            lines.append(("class:dim", f"    {' · '.join(meta_parts)}\n"))

        if not has_any and search:
            lines.append(("class:dim", "    No matching sessions\n"))

        lines.append(("", "\n"))

        # ── Keyboard shortcuts ──
        lines.append(("class:key-hint",
            "  ↑↓ select  ·  Enter resume  ·  Esc cancel  ·  Type to search  ·  Ctrl+A show all\n"))

        return lines

    # Printable key handler
    @kb.add("<any>")
    def _(e):
        nonlocal search, selected
        if e.data and len(e.data) == 1 and e.data.isprintable():
            search += e.data
            selected = 0

    content = FormattedTextControl(text=_render, focusable=True)
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
