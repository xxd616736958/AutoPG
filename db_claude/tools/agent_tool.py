"""Agent tool."""
import json
from pydantic import Field
from langchain_core.tools import tool

@tool
async def agent(
    description: str = Field(description="A short (3-5 word) description of the task"),
    prompt: str = Field(description="The task for the agent to perform"),
    subagent_type: str = Field(default=None, description="Type of specialized agent to use (Explore, Plan, general-purpose)"),
    run_in_background: bool = Field(default=False, description="Run agent asynchronously; you will be notified when it completes"),
) -> str:
    """Launch a subagent to handle complex multi-step tasks."""
    return json.dumps({"status":"launched","description":description,"subagent_type":subagent_type or "general-purpose","background":run_in_background})
