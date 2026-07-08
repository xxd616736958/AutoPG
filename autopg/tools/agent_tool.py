"""Forked subagent tool, modeled after AutoPG's Agent tool."""
import json
from typing import Annotated

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import InjectedToolArg, tool
from pydantic import Field


@tool
async def agent(
    description: str = Field(description="A short 3-5 word description of the subtask"),
    prompt: str = Field(description="The full task for the forked subagent to perform"),
    subagent_type: str = Field(default="general-purpose", description="Agent type: general-purpose, Explore, Plan, or a custom type"),
    run_in_background: bool = Field(default=False, description="Run asynchronously and return an agent_id immediately"),
    config: Annotated[RunnableConfig, InjectedToolArg] = None,
) -> str:
    """Launch a forked subagent with isolated context and filtered tools."""
    from ..agent.tools.agent_definitions import find_agent_definition, list_available_agents
    from ..agent.subagent import run_subagent_background, run_subagent_inline

    runtime_context = (config or {}).get("configurable", {}).get("_context")
    parent_engine = getattr(runtime_context, "_parent_engine", None) if runtime_context else None
    if parent_engine is None:
        return json.dumps({
            "status": "failed",
            "error": "Agent tool requires a parent QueryEngine context",
        }, ensure_ascii=False)

    agent_def = find_agent_definition(subagent_type or "general-purpose")
    if agent_def is None:
        return json.dumps({
            "status": "failed",
            "error": f"Unknown subagent_type: {subagent_type}",
            "available_types": [a.agent_type for a in list_available_agents()],
        }, ensure_ascii=False)

    if run_in_background:
        result = await run_subagent_background(parent_engine, agent_def, description, prompt)
    else:
        result = await run_subagent_inline(parent_engine, agent_def, prompt)
    return json.dumps(result, ensure_ascii=False, indent=2)
