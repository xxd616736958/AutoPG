"""Workflow tool."""
import json
from pydantic import Field
from langchain_core.tools import tool

@tool
async def workflow(
    name: str = Field(default=None, description="Name of a predefined workflow"),
    script: str = Field(default=None, description="Self-contained workflow script"),
) -> str:
    """Execute a workflow script that orchestrates multiple subagents deterministically."""
    return json.dumps({"status":"executed","name":name or "custom"})
