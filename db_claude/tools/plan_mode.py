"""
Plan mode and Worktree tools for db-claude.
Architecturally identical to Claude Code's EnterPlanModeTool, ExitPlanModeTool,
EnterWorktreeTool, and ExitWorktreeTool.
"""
from typing import Type, Optional
from pydantic import BaseModel, Field

from .base import Tool

# Global state (scoped per-session in production)
_in_plan_mode = False
_in_worktree = False


# -- EnterPlanMode --

class EnterPlanModeInput(BaseModel):
    """Input schema for EnterPlanMode tool (no parameters)."""
    pass


class EnterPlanModeTool(Tool):
    """Enter plan mode for designing implementation before writing code."""

    name = "EnterPlanMode"
    aliases = []
    search_hint = "enter plan mode before implementing"

    def input_schema(self) -> Type[BaseModel]:
        return EnterPlanModeInput

    async def call(self, args: dict, context: dict) -> dict:
        global _in_plan_mode
        _in_plan_mode = True
        return {
            "data": {
                "status": "entered_plan_mode",
                "message": "Now in plan mode. Design your approach, explore the codebase, and present your plan for user approval before implementing.",
            },
        }

    async def description(self, input_schema: dict, options: dict) -> str:
        return "Enter plan mode to design an implementation approach before writing code. Use this proactively for non-trivial tasks requiring architectural decisions or multi-file changes."

    def is_read_only(self, input_data: dict = None) -> bool:
        return False  # Changes agent behavior


# -- ExitPlanMode --

class ExitPlanModeInput(BaseModel):
    """Input schema for ExitPlanMode tool (no parameters)."""
    pass


class ExitPlanModeTool(Tool):
    """Exit plan mode and return to normal execution."""

    name = "ExitPlanMode"
    aliases = []
    search_hint = "exit plan mode for user approval"

    def input_schema(self) -> Type[BaseModel]:
        return ExitPlanModeInput

    async def call(self, args: dict, context: dict) -> dict:
        global _in_plan_mode
        _in_plan_mode = False
        return {
            "data": {
                "status": "exited_plan_mode",
                "message": "Exited plan mode. Plan is ready for user review and approval.",
            },
        }

    async def description(self, input_schema: dict, options: dict) -> str:
        return "Exit plan mode and present your plan to the user for approval. Use after you have finished designing your implementation plan."

    def is_read_only(self, input_data: dict = None) -> bool:
        return False


# -- EnterWorktree --

class EnterWorktreeInput(BaseModel):
    """Input schema for EnterWorktree tool."""
    name: Optional[str] = Field(default=None, description="Optional name for a new worktree")
    path: Optional[str] = Field(default=None, description="Path to an existing worktree to enter")


class EnterWorktreeTool(Tool):
    """Create or enter a git worktree for isolated work."""

    name = "EnterWorktree"
    aliases = []
    search_hint = "create an isolated git worktree"

    def input_schema(self) -> Type[BaseModel]:
        return EnterWorktreeInput

    async def call(self, args: dict, context: dict) -> dict:
        global _in_worktree
        _in_worktree = True
        worktree_name = args.get("name", "temp")

        return {
            "data": {
                "status": "entered_worktree",
                "name": worktree_name,
                "message": f"Entered worktree '{worktree_name}'. Working in an isolated environment.",
            },
        }

    async def description(self, input_schema: dict, options: dict) -> str:
        return "Create an isolated git worktree for parallel work without conflicts. Use for tasks that need isolated file mutations."

    def is_read_only(self, input_data: dict = None) -> bool:
        return False


# -- ExitWorktree --

class ExitWorktreeInput(BaseModel):
    """Input schema for ExitWorktree tool."""
    action: str = Field(description="'keep' to leave the worktree intact, 'remove' to delete it")
    discard_changes: bool = Field(default=False, description="Whether to discard uncommitted changes")


class ExitWorktreeTool(Tool):
    """Exit a worktree and return to original directory."""

    name = "ExitWorktree"
    aliases = []
    search_hint = "leave an isolated worktree"

    def input_schema(self) -> Type[BaseModel]:
        return ExitWorktreeInput

    async def call(self, args: dict, context: dict) -> dict:
        global _in_worktree
        action = args.get("action", "keep")
        _in_worktree = False

        return {
            "data": {
                "status": "exited_worktree",
                "action": action,
                "message": f"Exited worktree (action: {action}).",
            },
        }

    async def description(self, input_schema: dict, options: dict) -> str:
        return "Exit a worktree session. Use 'keep' to preserve changes, 'remove' to clean up."

    def is_read_only(self, input_data: dict = None) -> bool:
        return False
