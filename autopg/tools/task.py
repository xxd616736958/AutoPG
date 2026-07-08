"""Task tools + background subagent lifecycle helpers."""
import json
from datetime import datetime
from pydantic import Field
from langchain_core.tools import tool

_store = {}


def _json(data):
    return json.dumps(data, ensure_ascii=False, indent=2)


@tool
async def task_create(
    subject: str = Field(description="A brief title for the task"),
    description: str = Field(description="What needs to be done"),
) -> str:
    """Create a new task for tracking progress on complex multi-step tasks."""
    tid = f"task_{len(_store)+1}"
    _store[tid] = {"id": tid, "subject": subject, "description": description, "status": "pending", "created_at": datetime.now().isoformat()}
    return _json({"id": tid, "subject": subject, "status": "pending"})


@tool
async def task_update(
    task_id: str = Field(description="The ID of the task to update"),
    status: str = Field(default=None, description="New status: pending, in_progress, completed, deleted"),
) -> str:
    """Update a task's status."""
    t = _store.get(task_id)
    if not t:
        return _json({"error": f"Task not found: {task_id}"})
    if status:
        t["status"] = status
        t["updated_at"] = datetime.now().isoformat()
    return _json({"id": t["id"], "subject": t["subject"], "status": t["status"]})


@tool
async def task_list() -> str:
    """List tracked tasks and background subagents."""
    from ..agent.subagent import list_background_agents
    tasks = [{"id": t["id"], "subject": t["subject"], "status": t["status"]} for t in _store.values() if t["status"] != "deleted"]
    agents = [a.to_dict(include_result=False) for a in list_background_agents()]
    return _json({"count": len(tasks), "tasks": tasks, "background_agents": agents})


@tool
async def task_get(
    task_id: str = Field(description="The task ID or background agent ID to retrieve"),
) -> str:
    """Retrieve full details of a task or background subagent."""
    from ..agent.subagent import get_background_agent
    t = _store.get(task_id)
    if t:
        return _json(t)
    agent = get_background_agent(task_id)
    if agent:
        return _json(agent.to_dict(include_result=True))
    return _json({"error": f"Task not found: {task_id}"})


@tool
async def task_stop(
    task_id: str = Field(description="The task ID or background agent ID to stop"),
) -> str:
    """Stop a tracked task or cancel a running background subagent."""
    from ..agent.subagent import cancel_background_agent
    if cancel_background_agent(task_id):
        return _json({"id": task_id, "status": "cancelled"})
    t = _store.get(task_id)
    if t:
        t["status"] = "stopped"
        t["updated_at"] = datetime.now().isoformat()
        return _json({"id": task_id, "status": "stopped"})
    return _json({"error": f"Task not found: {task_id}"})


@tool
async def task_output(
    task_id: str = Field(description="The task ID or background agent ID to get output from"),
) -> str:
    """Retrieve output from a running or completed background subagent/task."""
    from ..agent.subagent import get_background_agent
    agent = get_background_agent(task_id)
    if agent:
        return _json(agent.to_dict(include_result=True))
    t = _store.get(task_id)
    if t:
        return _json(t)
    return _json({"error": f"Task not found: {task_id}"})
