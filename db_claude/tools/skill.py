"""
Skill tool for db-claude.
Architecturally identical to Claude Code's SkillTool.
"""
from typing import Type, Optional
from pydantic import BaseModel, Field

from .base import Tool


class SkillInput(BaseModel):
    """Input schema for Skill tool."""
    skill: str = Field(description="The name of a skill from the available-skills list. Do not guess names.")
    args: Optional[str] = Field(default=None, description="Optional arguments for the skill")


class SkillTool(Tool):
    """Execute a skill within the main conversation."""

    name = "Skill"
    aliases = []
    search_hint = "invoke a named skill"

    def input_schema(self) -> Type[BaseModel]:
        return SkillInput

    async def call(self, args: dict, context: dict) -> dict:
        skill_name = args.get("skill", "")
        skill_args = args.get("args", "")

        # In a real implementation, skills would be loaded from .claude/skills/
        # and the agent's system prompt. Here we provide the interface.

        return {
            "data": {
                "status": "invoked",
                "skill": skill_name,
                "args": skill_args,
                "message": f"Skill '{skill_name}' invoked with args: {skill_args}",
            },
        }

    async def description(self, input_schema: dict, options: dict) -> str:
        return "Execute a skill within the main conversation. Skills provide specialized capabilities and domain knowledge. Only use skills listed in the system prompt's available-skills section."

    def is_read_only(self, input_data: dict = None) -> bool:
        return False

    def get_activity_description(self, input_data: dict = None) -> str:
        if not input_data:
            return "Invoking skill"
        return f"Skill: {input_data.get('skill', '')}"
