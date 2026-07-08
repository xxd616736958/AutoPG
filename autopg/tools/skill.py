"""Skill tool."""
import json
from pydantic import Field
from langchain_core.tools import tool

@tool
async def skill(
    skill: str = Field(description="Name of a skill from the available-skills list"),
    args: str = Field(default=None, description="Optional arguments for the skill"),
) -> str:
    """Execute a named skill within the main conversation."""
    return json.dumps({"status":"invoked","skill":skill,"args":args})
