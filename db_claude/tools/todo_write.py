"""Todo tool."""
import json
from pydantic import Field
from langchain_core.tools import tool

@tool
async def todo_write(
    todos: list = Field(description="List of todo items, each with content (str) and status (pending/in_progress/completed)"),
) -> str:
    """Create and manage a structured task list for tracking progress on complex coding tasks."""
    counts = {"pending":0,"in_progress":0,"completed":0,"total":len(todos)}
    for t in todos:
        s = t.get("status","pending")
        if s in counts: counts[s] += 1
    return json.dumps({"counts":counts,"todos":[{"content":t.get("content",""),"status":t.get("status","pending")} for t in todos]})
