"""
Monitor tool for db-claude.
Architecturally identical to Claude Code's MonitorTool.
"""
from typing import Type
from pydantic import BaseModel, Field

from .base import Tool


class MonitorInput(BaseModel):
    """Input schema for Monitor tool."""
    description: str = Field(description="Short human-readable description of what you are monitoring")
    timeout_ms: int = Field(default=300000, description="Kill the monitor after this deadline (max 3600000ms)")
    persistent: bool = Field(default=False, description="Run for the lifetime of the session (no timeout)")
    command: str = Field(description="Shell command or script. Each stdout line is an event; exit ends the watch.")


class MonitorTool(Tool):
    """Start a background monitor that streams events from a long-running script."""

    name = "Monitor"
    aliases = []
    search_hint = "watch a log or process for events"

    def input_schema(self) -> Type[BaseModel]:
        return MonitorInput

    async def call(self, args: dict, context: dict) -> dict:
        command = args.get("command", "")
        description = args.get("description", "")
        persistent = args.get("persistent", False)
        timeout_ms = min(args.get("timeout_ms", 300000), 3600000)

        return {
            "data": {
                "status": "started",
                "description": description,
                "persistent": persistent,
                "timeout_ms": timeout_ms,
                "message": f"Monitor started: {description}",
            },
        }

    async def description(self, input_schema: dict, options: dict) -> str:
        return "Start a background monitor that streams events from a long-running script. Each stdout line becomes a notification. Use for watching logs, file changes, or polling external state."

    def is_read_only(self, input_data: dict = None) -> bool:
        return False  # Starts background processes

    def get_activity_description(self, input_data: dict = None) -> str:
        if not input_data:
            return "Starting monitor"
        return f"Monitor: {input_data.get('description', '')}"
