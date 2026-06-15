"""
Agent tool — full subagent execution matching Claude Code's AgentTool.
"""
from typing import Type, Optional
from pydantic import BaseModel, Field
from .base import Tool, PermissionResult


class AgentInput(BaseModel):
    description: str = Field(description="A short (3-5 word) description of the task")
    prompt: str = Field(description="The task for the agent to perform")
    subagent_type: Optional[str] = Field(default=None, description="The type of specialized agent to use")
    model: Optional[str] = Field(default=None, description="Optional model override for this agent")
    run_in_background: bool = Field(default=False, description="Run agent asynchronously")
    isolation: Optional[str] = Field(default=None, description="Isolation mode: 'worktree'")


class AgentTool(Tool):
    """Launch a subagent — full Claude Code AgentTool implementation."""

    name = "Agent"
    aliases = []
    search_hint = "spawn a subagent for complex multi-step tasks"

    def input_schema(self) -> Type[BaseModel]:
        return AgentInput

    async def call(self, args: dict, context: dict) -> dict:
        from ..agent.tools.agent_definitions import find_agent_definition, list_available_agents
        from ..agent.subagent import run_subagent_inline, run_subagent_background

        description = args.get("description", "subagent task")
        prompt = args.get("prompt", "")
        subagent_type = args.get("subagent_type", "general-purpose")
        run_in_background = args.get("run_in_background", False)

        # Get the parent engine from context
        parent_engine = context.get("_parent_engine")
        if not parent_engine:
            return {"data": "Error: Agent tool requires parent engine reference."}

        # Resolve agent definition
        agent_def = find_agent_definition(subagent_type)
        if not agent_def:
            available = [a.agent_type for a in list_available_agents()]
            return {"data": f"Unknown agent type: '{subagent_type}'. Available: {', '.join(available)}"}

        # Execute
        if run_in_background:
            result = await run_subagent_background(
                parent_engine, agent_def, description, prompt,
            )
        else:
            result = await run_subagent_inline(
                parent_engine, agent_def, prompt,
            )

        return {"data": result}

    async def description(self, input_schema: dict, options: dict) -> str:
        from ..agent.tools.agent_definitions import list_available_agents

        agents = list_available_agents()
        agent_lines = []
        for a in agents:
            agent_lines.append(f"- **{a.agent_type}**: {a.description}")
            if a.when_to_use:
                agent_lines.append(f"  When: {a.when_to_use}")

        return f"""Launch a new agent to handle complex, multi-step tasks. Each agent type has specific capabilities and tools available.

Available agent types:
{chr(10).join(agent_lines)}

## When to use
Reach for this when the task matches an available agent type, when you have independent work to run in parallel, or when answering would mean reading across several files — delegate it and you keep the conclusion, not the file dumps.

Use `isolation: 'worktree'` to give the agent its own git worktree.
Use `run_in_background: true` for asynchronous execution. You'll be notified when it completes."""

    def is_read_only(self, input_data: dict = None) -> bool:
        return False  # Agents can modify files

    def is_destructive(self, input_data: dict = None) -> bool:
        return False  # Agents are not inherently destructive

    def get_activity_description(self, input_data: dict = None) -> Optional[str]:
        if not input_data:
            return "Spawning agent"
        desc = input_data.get("description", "")
        agent_type = input_data.get("subagent_type", "general-purpose")
        bg = " (background)" if input_data.get("run_in_background") else ""
        return f"Agent: {desc} [{agent_type}]{bg}"

    def format_call(self, args: dict) -> str:
        desc = args.get("description", "task")[:40]
        agent_type = args.get("subagent_type", "")
        type_str = f":{agent_type}" if agent_type else ""
        return f"Agent({desc}{type_str})"

    def format_result(self, data) -> str:
        if not isinstance(data, dict):
            return str(data)[:120]
        status = data.get("status", "")
        if status == "started":
            return f"background agent started: {data.get('agent_id', '')[:12]}..."
        if status == "completed":
            result = data.get("result", "")
            lines = result.strip().split("\n")
            return lines[0][:120] if lines else "completed"
        if status == "failed":
            return f"failed: {data.get('error', 'unknown')[:120]}"
        return status

    async def check_permissions(self, input_data: dict, context: dict) -> PermissionResult:
        # Agent spawns are not destructive but should be confirmed in strict modes
        return PermissionResult(behavior="allow", updated_input=input_data)
