"""AskUser tool."""
import json
from pydantic import BaseModel, Field
from langchain_core.tools import tool

class Question(BaseModel):
    question: str = Field(description="The complete question")
    header: str = Field(description="Short label (max 12 chars)")
    options: list[dict] = Field(description="2-4 options with label and description")
    multi_select: bool = Field(default=False)
class AskInput(BaseModel):
    questions: list[dict] = Field(description="1-4 questions to ask")
@tool(args_schema=AskInput)
async def ask_user_question(questions: list) -> str:
    """Ask the user clarifying questions. Use when blocked on a decision only the user can make."""
    return json.dumps({"status":"presented","questions":questions})
