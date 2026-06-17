"""Plan/Worktree tools."""
import json
from pydantic import Field
from langchain_core.tools import tool

@tool
async def enter_plan_mode() -> str:
    """Enter plan mode to design an implementation approach before writing code."""
    return json.dumps({"status":"entered_plan_mode"})

@tool
async def exit_plan_mode() -> str:
    """Exit plan mode and present your plan to the user for approval."""
    return json.dumps({"status":"exited_plan_mode"})

@tool
async def enter_worktree(
    name: str = Field(default=None, description="Optional name for a new worktree"),
) -> str:
    """Create or enter an isolated git worktree for parallel work without conflicts."""
    return json.dumps({"status":"entered_worktree","name":name or "temp"})

@tool
async def exit_worktree(
    action: str = Field(default="keep", description="'keep' to leave worktree intact, 'remove' to delete it"),
) -> str:
    """Exit a worktree session and return to original directory."""
    return json.dumps({"status":"exited_worktree","action":action})
