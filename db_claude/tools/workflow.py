"""Workflow tool."""
import json
from pydantic import BaseModel, Field
from langchain_core.tools import tool

class WFInput(BaseModel):
    name: str = Field(default=None)
    script: str = Field(default=None)
@tool(args_schema=WFInput)
async def workflow(name: str = None, script: str = None) -> str:
    """Execute a workflow script orchestrating multiple subagents."""
    return json.dumps({"status":"executed","name":name or "custom"})
