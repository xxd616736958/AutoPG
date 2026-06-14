"""
AskUserQuestion tool for db-claude.
Architecturally identical to Claude Code's AskUserQuestionTool.
"""
from typing import Type
from pydantic import BaseModel, Field

from .base import Tool, PermissionResult


class QuestionOption(BaseModel):
    """An option for a question."""
    label: str = Field(description="The display text for this option")
    description: str = Field(description="Explanation of what this option means")


class Question(BaseModel):
    """A single question to ask."""
    question: str = Field(description="The complete question to ask the user")
    header: str = Field(description="Very short label displayed as a chip/tag (max 12 chars)")
    options: list[QuestionOption] = Field(description="The available choices (2-4 options)")
    multi_select: bool = Field(default=False, description="Allow multiple answers to be selected")


class AskUserQuestionInput(BaseModel):
    """Input schema for AskUserQuestion tool."""
    questions: list[Question] = Field(description="Questions to ask the user (1-4 questions)")


class AskUserQuestionTool(Tool):
    """Ask the user one or more questions to resolve ambiguity."""

    name = "AskUserQuestion"
    aliases = []
    search_hint = "ask the user clarifying questions"

    def input_schema(self) -> Type[BaseModel]:
        return AskUserQuestionInput

    async def call(self, args: dict, context: dict) -> dict:
        """Present questions to the user."""
        questions = args.get("questions", [])

        return {
            "data": {
                "status": "presented",
                "questions": questions,
                "message": "Questions presented to user for input.",
            },
        }

    async def description(self, input_schema: dict, options: dict) -> str:
        return "Ask the user one or more questions when blocked on a decision only the user can make. Use for clarifying requirements, choosing between approaches, or resolving ambiguities."

    def is_read_only(self, input_data: dict = None) -> bool:
        return True

    def requires_user_interaction(self) -> bool:
        return True
