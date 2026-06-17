"""Task tools."""
import json
from datetime import datetime
from pydantic import Field
from langchain_core.tools import tool

_store = {}

@tool
async def task_create(
    subject: str = Field(description="A brief title for the task"),
    description: str = Field(description="What needs to be done"),
) -> str:
    """Create a new task for tracking progress on complex multi-step tasks."""
    tid = f"task_{len(_store)+1}"
    _store[tid] = {"id": tid, "subject": subject, "description": description, "status": "pending", "created_at": datetime.now().isoformat()}
    return json.dumps({"id": tid, "subject": subject, "status": "pending"})

@tool
async def task_update(
    task_id: str = Field(description="The ID of the task to update"),
    status: str = Field(default=None, description="New status: pending, in_progress, completed, deleted"),
) -> str:
    """Update a task's status."""
    t = _store.get(task_id)
    if not t: return json.dumps(f"Error: Task not found: {task_id}")
    if status: t["status"] = status; t["updated_at"] = datetime.now().isoformat()
    return json.dumps({"id": t["id"], "subject": t["subject"], "status": t["status"]})

@tool
async def task_list() -> str:
    """List all tasks and their statuses."""
    tasks = [{"id": t["id"], "subject": t["subject"], "status": t["status"]} for t in _store.values() if t["status"] != "deleted"]
    return json.dumps({"count": len(tasks), "tasks": tasks})

@tool
async def task_get(
    task_id: str = Field(description="The ID of the task to retrieve"),
) -> str:
    """Retrieve full details of a task by its ID."""
    t = _store.get(task_id)
    return json.dumps(t if t else f"Error: Task not found: {task_id}")

@tool
async def task_stop(
    task_id: str = Field(description="The ID of the background task to stop"),
) -> str:
    """Stop a running background task."""
    t = _store.get(task_id)
    if t: t["status"] = "stopped"; return json.dumps({"id": task_id, "status": "stopped"})
    return json.dumps(f"Error: Task not found: {task_id}")

@tool
async def task_output(
    task_id: str = Field(description="The task ID to get output from"),
) -> str:
    """Retrieve output from a running or completed background task."""
    t = _store.get(task_id)
    return json.dumps(t if t else f"Error: Task not found: {task_id}")
