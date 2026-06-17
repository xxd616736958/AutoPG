"""Skill tool."""
import json
from pydantic import BaseModel, Field
from langchain_core.tools import tool

class SkillInput(BaseModel):
    skill: str = Field(description="Name of the skill from the available-skills list")
    args: str = Field(default=None)
@tool(args_schema=SkillInput)
async def skill(skill: str, args: str = None) -> str:
    """Execute a named skill within the conversation."""
    return json.dumps({"status":"invoked","skill":skill,"args":args})
