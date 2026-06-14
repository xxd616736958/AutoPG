"""
TodoWrite tool for db-claude.
Architecturally identical to Claude Code's TodoWriteTool.
"""
from typing import Type
from pydantic import BaseModel, Field

from .base import Tool


class TodoWriteInput(BaseModel):
    """Input schema for TodoWrite tool."""
    todos: list[dict] = Field(description="List of todo items, each with content, status (pending/in_progress/completed), and optional active_form")


class TodoWriteTool(Tool):
    """Create and manage a structured task list."""

    name = "TodoWrite"
    aliases = []
    search_hint = "create and update a structured task list"

    def input_schema(self) -> Type[BaseModel]:
        return TodoWriteInput

    async def call(self, args: dict, context: dict) -> dict:
        todos = args.get("todos", [])
        counts = {"pending": 0, "in_progress": 0, "completed": 0, "total": len(todos)}

        for todo in todos:
            status = todo.get("status", "pending")
            if status in counts:
                counts[status] += 1

        return {
            "data": {
                "counts": counts,
                "todos": [
                    {
                        "content": t.get("content", ""),
                        "status": t.get("status", "pending"),
                    }
                    for t in todos
                ],
            },
        }

    async def description(self, input_schema: dict, options: dict) -> str:
        return "Create and manage a structured task list for tracking progress on complex coding tasks. Use to plan and communicate progress to the user."

    def is_read_only(self, input_data: dict = None) -> bool:
        return True  # Display-only in most contexts
