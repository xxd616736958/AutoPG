"""Todo tool."""
import json
from pydantic import BaseModel, Field
from langchain_core.tools import tool

class TodoInput(BaseModel):
    todos: list[dict] = Field(description="List of todo items with content and status")
@tool(args_schema=TodoInput)
async def todo_write(todos: list) -> str:
    """Create and manage a structured task list for tracking progress."""
    counts = {"pending":0,"in_progress":0,"completed":0,"total":len(todos)}
    for t in todos:
        s = t.get("status","pending")
        if s in counts: counts[s] += 1
    return json.dumps({"counts":counts,"todos":[{"content":t.get("content",""),"status":t.get("status","pending")} for t in todos]})
