"""
Session persistence — AutoPG's recordTranscript architecture.
Sequential JSONL transcript per session. No checkpoints needed.
"""
import os, json, glob, asyncio, subprocess
from typing import Optional
from datetime import datetime
from pathlib import Path
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage, SystemMessage


def get_sessions_dir() -> str:
    base = os.environ.get("AUTOPG_CONFIG_DIR", os.path.expanduser("~/.autopg"))
    return os.path.join(base, "sessions")

def _ensure_dir(): os.makedirs(get_sessions_dir(), exist_ok=True)

def get_transcript_path(session_id: str) -> str:
    """AutoPG: getTranscriptPathForSession()"""
    return os.path.join(get_sessions_dir(), f"{session_id}.jsonl")

# ── Serialization (matching AutoPG's SerializedMessage) ──

def _serialize(msg) -> dict:
    """Convert a LangChain message to a JSON-serializable dict."""
    from langchain_core.messages import HumanMessage, AIMessage, ToolMessage, SystemMessage

    entry: dict = {
        "type": _msg_type(msg),
        "content": _msg_content(msg),
        "timestamp": datetime.now().isoformat(),
        "uuid": str(msg.additional_kwargs.get("uuid", "")) if hasattr(msg, "additional_kwargs") and msg.additional_kwargs else "",
    }

    if isinstance(msg, AIMessage):
        tc = getattr(msg, "tool_calls", None) or []
        if tc:
            entry["tool_calls"] = [{"name": t.get("name", ""), "args": t.get("args", {}), "id": t.get("id", "")} for t in tc]
    elif isinstance(msg, ToolMessage):
        entry["tool_call_id"] = getattr(msg, "tool_call_id", "")
        entry["tool_name"] = getattr(msg, "name", "")
    elif isinstance(msg, SystemMessage):
        subtype = (msg.additional_kwargs or {}).get("subtype", "")
        if subtype:
            entry["subtype"] = subtype

    return entry

def _msg_type(msg) -> str:
    if isinstance(msg, HumanMessage): return "user"
    if isinstance(msg, AIMessage): return "assistant"
    if isinstance(msg, ToolMessage): return "user"
    if isinstance(msg, SystemMessage): return "system"
    return "unknown"

def _msg_content(msg) -> str:
    content = getattr(msg, "content", str(msg))
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                parts.append(block.get("text", block.get("content", str(block))))
            else:
                parts.append(str(block))
        return "\n".join(parts)
    return str(content) if content else ""

# ── Write (AutoPG: enqueueWrite / recordTranscript) ──

# In-memory write queue for this process
_write_queue: dict[str, list[dict]] = {}
_flush_tasks: dict[str, asyncio.Task] = {}

async def _flush_deferred(filepath: str):
    """Flush buffered entries to disk after 100ms (AutoPG's lazy flush)."""
    await asyncio.sleep(0.1)
    entries = _write_queue.pop(filepath, [])
    if not entries:
        return
    try:
        with open(filepath, "a", encoding="utf-8") as f:
            for entry in entries:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass

def enqueue_write(session_id: str, entry: dict, await_flush: bool = False):
    """Append a serialized entry to the session transcript.
    Fire-and-forget by default (matches AutoPG's lazy flush for UI responsiveness).
    Set await_flush=True for critical writes (user messages before API call)."""
    _ensure_dir()
    filepath = get_transcript_path(session_id)
    if filepath not in _write_queue:
        _write_queue[filepath] = []
    _write_queue[filepath].append(entry)

    # Cancel existing flush task, start new one
    if filepath in _flush_tasks and not _flush_tasks[filepath].done():
        _flush_tasks[filepath].cancel()
    task = asyncio.create_task(_flush_deferred(filepath))
    _flush_tasks[filepath] = task

def flush_session_now(session_id: str):
    """Synchronously flush all buffered entries (for shutdown)."""
    filepath = get_transcript_path(session_id)
    entries = _write_queue.pop(filepath, [])
    if not entries:
        return
    _ensure_dir()
    try:
        with open(filepath, "a", encoding="utf-8") as f:
            for entry in entries:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass

async def record_transcript(session_id: str, messages: list, await_write: bool = False):
    """Write multiple messages to transcript. AutoPG: recordTranscript().
    Called after each turn. await_write=True for critical writes."""
    for msg in messages:
        enqueue_write(session_id, _serialize(msg))
    if await_write:
        flush_session_now(session_id)

# ── Metadata (AutoPG: reAppendSessionMetadata) ──

def write_session_metadata(session_id: str, metadata: dict):
    """Write session metadata as a JSON sidecar file."""
    _ensure_dir()
    path = os.path.join(get_sessions_dir(), f"{session_id}.meta.json")
    existing = {}
    if os.path.exists(path):
        try:
            with open(path) as f:
                existing = json.load(f)
        except: pass
    existing.update(metadata)
    with open(path, "w") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)

def read_session_metadata(session_id: str) -> dict:
    path = os.path.join(get_sessions_dir(), f"{session_id}.meta.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except: return {}

# ── Read / Resume (AutoPG: hydrateFromTranscript) ──

def load_transcript(session_id: str) -> Optional[dict]:
    """Load full transcript as structured data."""
    path = get_transcript_path(session_id)
    if not os.path.exists(path):
        return None
    try:
        entries = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
        meta = read_session_metadata(session_id)
        return {
            "session_id": session_id,
            "message_count": len(entries),
            "messages": entries,
            "metadata": meta,
            "saved_at": meta.get("saved_at", ""),
        }
    except (json.JSONDecodeError, IOError):
        return None

def list_sessions(limit: int = 50) -> list[dict]:
    """List sessions with metadata, newest first. AutoPG: listSessions()."""
    _ensure_dir()
    files = sorted(
        glob.glob(os.path.join(get_sessions_dir(), "*.jsonl")),
        key=os.path.getmtime, reverse=True,
    )[:limit]

    sessions = []
    for fpath in files:
        sid = os.path.basename(fpath)[:-6]  # Remove .jsonl
        try:
            with open(fpath, "r") as f:
                first_line = f.readline()
                first = json.loads(first_line) if first_line.strip() else {}
            stat = os.stat(fpath)
            meta = read_session_metadata(sid)
            # Extract title from first user message
            title = ""
            if first.get("type") == "user":
                content = first.get("content", "")
                if isinstance(content, str):
                    title = content.strip().split("\n")[0][:80]
            sessions.append({
                "session_id": sid,
                "saved_at": meta.get("saved_at", datetime.fromtimestamp(stat.st_mtime).isoformat()),
                "message_count": meta.get("message_count", 0),
                "size_bytes": stat.st_size,
                "title": title or meta.get("title", ""),
                "branch": meta.get("branch", ""),
            })
        except (json.JSONDecodeError, IOError):
            continue
    return sessions

def session_id_exists(session_id: str) -> bool:
    return os.path.exists(get_transcript_path(session_id))

def get_last_session_id() -> Optional[str]:
    sessions = list_sessions(limit=1)
    return sessions[0]["session_id"] if sessions else None

def delete_session(session_id: str) -> bool:
    path = get_transcript_path(session_id)
    meta_path = os.path.join(get_sessions_dir(), f"{session_id}.meta.json")
    deleted = False
    if os.path.exists(path): os.remove(path); deleted = True
    if os.path.exists(meta_path): os.remove(meta_path)
    return deleted

def resume_messages(session_id: str) -> list:
    """Restore LangChain messages from transcript. AutoPG: hydrateSession()."""
    data = load_transcript(session_id)
    if not data:
        return []

    messages = []
    for entry in data.get("messages", []):
        msg_type = entry.get("type", "")
        content = entry.get("content", "")
        tool_calls = entry.get("tool_calls", [])

        if msg_type == "user":
            tool_call_id = entry.get("tool_call_id", "")
            if tool_call_id:
                msg = ToolMessage(
                    content=str(content),
                    tool_call_id=tool_call_id,
                    name=entry.get("tool_name", ""),
                )
            else:
                msg = HumanMessage(content=str(content))
        elif msg_type == "assistant":
            msg = AIMessage(content=str(content))
            if tool_calls:
                msg.tool_calls = tool_calls
        elif msg_type == "system":
            subtype = entry.get("subtype", "")
            msg = SystemMessage(content=str(content), additional_kwargs={"subtype": subtype})
        else:
            continue
        messages.append(msg)

    return messages

# ── Auto-extract metadata ──

def _extract_title(messages: list) -> str:
    for msg in messages:
        if isinstance(msg, HumanMessage) and not (msg.additional_kwargs or {}).get("is_meta"):
            content = str(getattr(msg, "content", ""))
            if content:
                return content.strip().split("\n")[0][:80]
    return ""

def _extract_branch(cwd: str) -> str:
    if not cwd: return ""
    try:
        r = subprocess.run(["git", "-C", cwd, "branch", "--show-current"],
                         capture_output=True, text=True, timeout=3)
        return r.stdout.strip() if r.returncode == 0 else ""
    except: return ""

def save_session(session_id: str, messages: list, metadata: dict = None, *, await_write: bool = False):
    """Save complete session. Writes transcript + metadata.
    AutoPG: combination of recordTranscript + reAppendSessionMetadata."""
    _ensure_dir()

    title = _extract_title(messages)
    branch = ""
    if metadata and metadata.get("cwd"):
        branch = _extract_branch(metadata["cwd"])

    entry_count = 0
    path = get_transcript_path(session_id)
    # Write all messages as a complete transcript (overwrite for simplicity;
    # in production would use enqueueWrite for incremental writes)
    try:
        with open(path, "w", encoding="utf-8") as f:
            for msg in messages:
                entry = _serialize(msg)
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                entry_count += 1
    except Exception:
        pass

    meta = {
        **(metadata or {}),
        "title": title,
        "branch": branch,
        "saved_at": datetime.now().isoformat(),
        "message_count": entry_count,
    }
    write_session_metadata(session_id, meta)

# Legacy alias
load_session = load_transcript
