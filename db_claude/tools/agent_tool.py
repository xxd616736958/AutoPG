"""
Agent tool for db-claude.
Architecturally identical to Claude Code's AgentTool (src/tools/AgentTool/).
Enables spawning subagents for parallel/distributed work.
"""
from typing import Type, Optional
from pydantic import BaseModel, Field

from .base import Tool


class AgentInput(BaseModel):
    """Input schema for Agent tool."""
    description: str = Field(description="A short (3-5 word) description of the task")
    prompt: str = Field(description="The task for the agent to perform")
    subagent_type: Optional[str] = Field(default=None, description="The type of specialized agent to use")
    run_in_background: bool = Field(default=False, description="Run agent asynchronously")
    isolation: Optional[str] = Field(default=None, description="Isolation mode: 'worktree' for git worktree")
    model: Optional[str] = Field(default=None, description="Optional model override for this agent")


class AgentTool(Tool):
    """Launch a subagent to handle complex, multi-step tasks."""

    name = "Agent"
    aliases = []
    search_hint = "spawn a subagent for complex tasks"

    def input_schema(self) -> Type[BaseModel]:
        return AgentInput

    async def call(self, args: dict, context: dict) -> dict:
        """Spawn a subagent for the requested task."""
        subagent_type = args.get("subagent_type", "general-purpose")
        prompt = args.get("prompt", "")
        description = args.get("description", "")
        run_in_background = args.get("run_in_background", False)

        # In a full implementation, this would spawn a new QueryEngine with
        # its own tool set and message history. Here we provide the interface.

        return {
            "data": {
                "status": "launched",
                "description": description,
                "subagent_type": subagent_type,
                "background": run_in_background,
                "message": f"Subagent '{description}' launched as {subagent_type}.",
            },
        }

    async def description(self, input_schema: dict, options: dict) -> str:
        return """Launch a new agent to handle complex, multi-step tasks. Each agent type has specific capabilities.

Available agent types:
- **general-purpose**: For complex questions, code search, and multi-step tasks.
- **Explore**: Read-only search agent for broad fan-out searches across files/directories.
- **Plan**: Software architect for designing implementation plans.

Use `isolation: 'worktree'` to give the agent its own git worktree for parallel file mutations.
Use `run_in_background: true` for asynchronous execution."""

    def is_read_only(self, input_data: dict = None) -> bool:
        return False  # Agents can modify files

    def get_activity_description(self, input_data: dict = None) -> str:
        if not input_data:
            return "Spawning agent"
        return f"Agent: {input_data.get('description', '')}"
