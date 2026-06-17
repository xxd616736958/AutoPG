"""Agent tool."""
import json
from pydantic import BaseModel, Field
from langchain_core.tools import tool

class AgentInput(BaseModel):
    description: str = Field(description="Short (3-5 word) description of the task")
    prompt: str = Field(description="The task for the agent to perform")
    subagent_type: str = Field(default=None, description="Type of specialized agent")
    run_in_background: bool = Field(default=False)
@tool(args_schema=AgentInput)
async def agent(description: str, prompt: str, subagent_type: str = None, run_in_background: bool = False) -> str:
    """Launch a subagent for complex multi-step tasks."""
    return json.dumps({"status":"launched","description":description,"subagent_type":subagent_type or "general-purpose","background":run_in_background})
