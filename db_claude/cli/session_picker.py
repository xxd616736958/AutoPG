"""
Session picker — Claude Code-style interactive session browser.
Renders a searchable, navigable list of saved sessions.
"""
import os, sys, time
from typing import Optional
from datetime import datetime

from prompt_toolkit import Application
from prompt_toolkit.layout import Layout, HSplit, Window, FormattedTextControl
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.containers import HSplit, VSplit, Window, WindowAlign
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.styles import Style
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.widgets import TextArea

from ..utils.session import list_sessions, load_session, resume_messages


STYLE = Style.from_dict({
    "header": "bold",
    "selected": "bg:#4444ff #ffffff",
    "dim": "#888888",
    "search-box": "bg:#333333 #ffffff",
    "preview": "#aaaaaa",
    "key-hint": "#666666",
})


def _time_ago(iso_str: str) -> str:
    """Convert ISO timestamp to human-readable relative time."""
    try:
        dt = datetime.fromisoformat(iso_str)
        now = datetime.now()
        diff = now - dt
        if diff.days > 30: return f"{diff.days // 30} months ago"
        if diff.days > 0: return f"{diff.days} days ago"
        hours = diff.seconds // 3600
        if hours > 0: return f"{hours} hours ago"
        mins = diff.seconds // 60
        if mins > 0: return f"{mins} minutes ago"
        return "just now"
    except:
        return ""


def _format_size(size_bytes: int) -> str:
    if size_bytes > 1024 * 1024: return f"{size_bytes / (1024*1024):.1f}MB"
    if size_bytes > 1024: return f"{size_bytes / 1024:.1f}KB"
    return f"{size_bytes}B"


async def pick_session(current_session_id: str = None) -> Optional[str]:
    """
    Open interactive session picker.
    Returns selected session_id, or None if cancelled.
    """

    sessions = list_sessions(limit=200)
    if not sessions:
        print("No saved sessions found.")
        return None

    # State
    selected_idx = 0
    search_text = ""
    preview_session_id = None
    preview_text_lines = ["", "Press Space to preview a session"]

    def get_filtered():
        if not search_text:
            return sessions
        q = search_text.lower()
        return [s for s in sessions if q in s["session_id"].lower() or q in str(s.get("saved_at", "")).lower()]

    kb = KeyBindings()

    @kb.add("up")
    def move_up(event):
        nonlocal selected_idx
        selected_idx = max(0, selected_idx - 1)

    @kb.add("down")
    def move_down(event):
        nonlocal selected_idx
        filtered = get_filtered()
        selected_idx = min(len(filtered) - 1, selected_idx + 1)

    @kb.add("escape")
    def cancel(event):
        nonlocal selected_idx
        selected_idx = -1  # Signal cancel
        event.app.exit()

    @kb.add("enter")
    def confirm(event):
        event.app.exit()

    @kb.add("space")
    def preview(event):
        nonlocal preview_session_id, preview_text_lines
        filtered = get_filtered()
        if 0 <= selected_idx < len(filtered):
            sid = filtered[selected_idx]["session_id"]
            preview_session_id = sid
            data = load_session(sid)
            if data:
                msgs = data.get("messages", [])
                lines = [f"Session: {sid[:24]}...", f"Messages: {len(msgs)}", ""]
                for m in msgs[-10:]:
                    content = str(m.get("content", ""))[:100]
                    role = m.get("type", "?")
                    lines.append(f"  [{role}] {content}")
                preview_text_lines = lines
            else:
                preview_text_lines = ["Failed to load session."]

    # Real-time search
    @kb.add("<any>")
    def type_char(event):
        nonlocal search_text, selected_idx
        if event.data and len(event.data) == 1 and event.data.isprintable():
            search_text += event.data
            selected_idx = 0

    @kb.add("backspace")
    def backspace(event):
        nonlocal search_text, selected_idx
        search_text = search_text[:-1]
        selected_idx = 0

    @kb.add("c-a")  # Ctrl+A
    def show_all(_):
        nonlocal search_text
        search_text = ""

    def build_display():
        filtered = get_filtered()
        lines = []

        # Header
        lines.append(FormattedText([("class:header", "  Resume session")]))
        lines.append(FormattedText([("", "─" * 100)]))

        # Search box
        search_display = search_text if search_text else "⌕ Search…"
        lines.append(FormattedText([
            ("class:search-box", f"  {search_display}")
        ]))
        lines.append(FormattedText([("", "")]))

        # Session list
        for i, s in enumerate(filtered[:50]):
            prefix = "❯" if i == selected_idx else " "
            sid = s["session_id"][:16]
            ago = _time_ago(s.get("saved_at", ""))
            size = _format_size(s.get("size_bytes", 0))
            msgs = s.get("message_count", 0)
            is_current = s["session_id"] == current_session_id

            line = f"  {prefix} {sid}...  "
            line += f"{msgs} msgs · {size}"
            if ago: line += f" · {ago}"
            if is_current: line += "  ← current"

            style = "class:selected" if i == selected_idx else ""
            lines.append(FormattedText([(style, line)]))

        # Footer
        lines.append(FormattedText([("", "")]))
        lines.append(FormattedText([("", "─" * 100)]))
        lines.append(FormattedText([
            ("class:key-hint", "  ↑↓ navigate  ·  Enter select  ·  Esc cancel  ·  Space preview  ·  Type to search")
        ]))

        # Preview pane
        if preview_session_id and len(filtered) > 0:
            lines.append(FormattedText([("", "")]))
            lines.append(FormattedText([("", "─" * 100)]))
            lines.append(FormattedText([("class:header", "  Preview")]))
            for pl in preview_text_lines[:15]:
                lines.append(FormattedText([("class:preview", f"  {pl}")]))

        return lines

    # Build application
    content = FormattedTextControl(
        text=lambda: build_display(),
        focusable=True,
    )

    root = Window(content=content, always_hide_cursor=True)
    layout = Layout(root)

    app = Application(
        layout=layout,
        key_bindings=kb,
        style=STYLE,
        full_screen=False,
    )

    await app.run_async()

    if selected_idx < 0:
        return None  # Cancelled

    filtered = get_filtered()
    if 0 <= selected_idx < len(filtered):
        return filtered[selected_idx]["session_id"]

    return None
