"""AskUser tool."""
import json
from pydantic import Field
from langchain_core.tools import tool

@tool
async def ask_user_question(
    questions: list = Field(description="1-4 questions, each with question, header, options (list of {label,description}), and optional multi_select"),
) -> str:
    """Ask the user clarifying questions. Use when blocked on a decision only the user can make."""
    return json.dumps({"status":"presented","questions":questions})
