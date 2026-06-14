"""
Session persistence for db-claude.
Architecturally mirrors Claude Code's sessionStorage (src/utils/sessionStorage.ts).
Saves/restores conversation transcripts with message history, usage, and metadata.
"""
import os
import json
import glob
from datetime import datetime
from typing import Optional
from pathlib import Path


def get_sessions_dir() -> str:
    """Get the sessions storage directory."""
    base = os.environ.get(
        "DB_CLAUDE_CONFIG_DIR",
        os.path.expanduser("~/.db-claude"),
    )
    return os.path.join(base, "sessions")


def _ensure_dir():
    os.makedirs(get_sessions_dir(), exist_ok=True)


def get_session_path(session_id: str) -> str:
    """Get the file path for a session."""
    return os.path.join(get_sessions_dir(), f"{session_id}.json")


def save_session(
    session_id: str,
    messages: list,
    metadata: Optional[dict] = None,
) -> str:
    """
    Save a session transcript to disk.
    Auto-extracts title from first user message and git branch from cwd.
    """
    _ensure_dir()

    # Auto-extract session title from first human message
    title = ""
    for msg in messages:
        if _msg_type(msg) == "human":
            content = _msg_content(msg)
            if content:
                first_line = content.strip().split("\n")[0].strip()
                title = first_line[:80]
            break

    # Auto-detect git branch
    branch = ""
    cwd = (metadata or {}).get("cwd", "")
    if cwd:
        try:
            import subprocess
            r = subprocess.run(["git", "-C", cwd, "branch", "--show-current"],
                             capture_output=True, text=True, timeout=3)
            if r.returncode == 0:
                branch = r.stdout.strip()
        except Exception:
            pass

    serialized = []
    for msg in messages:
        entry = {
            "type": _msg_type(msg),
            "content": _msg_content(msg),
            "timestamp": datetime.now().isoformat(),
        }

        # Save tool calls if present
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            entry["tool_calls"] = [
                {"name": tc.get("name", ""), "args": tc.get("args", {})}
                for tc in msg.tool_calls
            ]

        # Save additional kwargs
        if hasattr(msg, "additional_kwargs") and msg.additional_kwargs:
            entry["meta"] = {
                k: v for k, v in msg.additional_kwargs.items()
                if isinstance(v, (str, int, float, bool, type(None)))
            }

        serialized.append(entry)

    data = {
        "session_id": session_id,
        "saved_at": datetime.now().isoformat(),
        "message_count": len(serialized),
        "messages": serialized,
        "metadata": {
            **(metadata or {}),
            "title": title,
            "branch": branch,
        },
    }

    path = get_session_path(session_id)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    return path


def load_session(session_id: str) -> Optional[dict]:
    """Load a session transcript from disk."""
    path = get_session_path(session_id)
    if not os.path.exists(path):
        return None

    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


def list_sessions(limit: int = 20) -> list[dict]:
    """List recent sessions, ordered by save time (newest first)."""
    _ensure_dir()
    session_files = sorted(
        glob.glob(os.path.join(get_sessions_dir(), "*.json")),
        key=os.path.getmtime,
        reverse=True,
    )[:limit]

    sessions = []
    for fpath in session_files:
        try:
            with open(fpath, "r") as f:
                data = json.load(f)
            stat = os.stat(fpath)
            meta = data.get("metadata", {})
            sessions.append({
                "session_id": data.get("session_id", os.path.basename(fpath)[:-5]),
                "saved_at": data.get("saved_at", ""),
                "message_count": data.get("message_count", 0),
                "size_bytes": stat.st_size,
                "title": meta.get("title", ""),
                "branch": meta.get("branch", ""),
            })
        except (json.JSONDecodeError, IOError):
            continue

    return sessions


def get_last_session_id() -> Optional[str]:
    """Get the most recently saved session ID."""
    sessions = list_sessions(limit=1)
    return sessions[0]["session_id"] if sessions else None


def delete_session(session_id: str) -> bool:
    """Delete a saved session."""
    path = get_session_path(session_id)
    if os.path.exists(path):
        os.remove(path)
        return True
    return False


def resume_messages(session_id: str) -> list:
    """
    Restore LangChain messages from a saved session.
    Returns list of BaseMessage objects ready for the agent.
    """
    from langchain_core.messages import HumanMessage, AIMessage, ToolMessage, SystemMessage

    data = load_session(session_id)
    if not data:
        return []

    messages = []
    for entry in data.get("messages", []):
        msg_type = entry.get("type", "")
        content = entry.get("content", "")
        meta = entry.get("meta", {})
        tool_calls = entry.get("tool_calls", [])

        if msg_type == "human":
            msg = HumanMessage(content=content, additional_kwargs=meta)
        elif msg_type == "ai":
            msg = AIMessage(content=content, additional_kwargs=meta)
            if tool_calls:
                msg.tool_calls = tool_calls
        elif msg_type == "tool":
            msg = ToolMessage(
                content=content,
                tool_call_id=meta.get("tool_call_id", ""),
                name=meta.get("name", ""),
            )
        elif msg_type == "system":
            msg = SystemMessage(content=content, additional_kwargs=meta)
        else:
            continue

        messages.append(msg)

    return messages


def _msg_type(msg) -> str:
    """Get message type string for serialization."""
    from langchain_core.messages import HumanMessage, AIMessage, ToolMessage, SystemMessage
    if isinstance(msg, HumanMessage):
        return "human"
    elif isinstance(msg, AIMessage):
        return "ai"
    elif isinstance(msg, ToolMessage):
        return "tool"
    elif isinstance(msg, SystemMessage):
        return "system"
    return "unknown"


def _msg_content(msg) -> str:
    """Get message content for serialization."""
    content = msg.content if hasattr(msg, "content") else str(msg)
    if isinstance(content, list):
        # Handle content blocks
        parts = []
        for block in content:
            if isinstance(block, dict):
                parts.append(block.get("text", str(block)))
            else:
                parts.append(str(block))
        return "\n".join(parts)
    return str(content) if content else ""
