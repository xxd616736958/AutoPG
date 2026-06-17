"""Plan/Worktree tools."""
import json
from pydantic import BaseModel, Field
from langchain_core.tools import tool

class Empty(BaseModel): pass
@tool(args_schema=Empty)
async def enter_plan_mode() -> str:
    """Enter plan mode to design implementation before writing code."""
    return json.dumps({"status":"entered_plan_mode"})

@tool(args_schema=Empty)
async def exit_plan_mode() -> str:
    """Exit plan mode and present plan for user approval."""
    return json.dumps({"status":"exited_plan_mode"})

class WTInput(BaseModel):
    name: str = Field(default=None, description="Optional name for new worktree")
@tool(args_schema=WTInput)
async def enter_worktree(name: str = None) -> str:
    """Create or enter an isolated git worktree."""
    return json.dumps({"status":"entered_worktree","name":name or "temp"})

class ExitWTInput(BaseModel):
    action: str = Field(description="'keep' or 'remove'")
@tool(args_schema=ExitWTInput)
async def exit_worktree(action: str = "keep") -> str:
    """Exit a worktree session."""
    return json.dumps({"status":"exited_worktree","action":action})
