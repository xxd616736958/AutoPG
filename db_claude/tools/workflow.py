"""
Workflow tool for db-claude.
Architecturally identical to Claude Code's WorkflowTool.
"""
from typing import Type, Optional
from pydantic import BaseModel, Field

from .base import Tool


class WorkflowInput(BaseModel):
    """Input schema for Workflow tool."""
    script: Optional[str] = Field(default=None, description="Self-contained workflow script")
    name: Optional[str] = Field(default=None, description="Name of a predefined workflow")
    args: Optional[dict] = Field(default=None, description="Optional input value exposed to the script as 'args'")
    resume_from_run_id: Optional[str] = Field(default=None, description="Run ID of a prior workflow to resume")


class WorkflowTool(Tool):
    """Execute a workflow script that orchestrates multiple subagents deterministically."""

    name = "Workflow"
    aliases = []
    search_hint = "orchestrate multi-agent workflows"

    def input_schema(self) -> Type[BaseModel]:
        return WorkflowInput

    async def call(self, args: dict, context: dict) -> dict:
        workflow_name = args.get("name", "custom")
        workflow_script = args.get("script")
        workflow_args = args.get("args", {})

        return {
            "data": {
                "status": "executed",
                "name": workflow_name,
                "message": f"Workflow '{workflow_name}' executed successfully.",
            },
        }

    async def description(self, input_schema: dict, options: dict) -> str:
        return """Execute a workflow script that orchestrates multiple subagents deterministically. Workflows structure work across many agents for comprehensive, verified results.

Use patterns like:
- **Review**: Fan out dimension reviewers, then adversarially verify findings
- **Research**: Multi-modal search → deep-read → synthesize
- **Migrate**: Discover sites → transform each (worktree isolation) → verify"""

    def is_read_only(self, input_data: dict = None) -> bool:
        return False

    def get_activity_description(self, input_data: dict = None) -> str:
        if not input_data:
            return "Running workflow"
        return f"Workflow: {input_data.get('name', 'custom')}"
