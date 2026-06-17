"""Monitor tool."""
import json
from pydantic import BaseModel, Field
from langchain_core.tools import tool

class MonitorInput(BaseModel):
    description: str = Field(description="Short description of what you are monitoring")
    timeout_ms: int = Field(default=300000, le=3600000)
    persistent: bool = Field(default=False)
    command: str = Field(description="Shell command; each stdout line is an event")
@tool(args_schema=MonitorInput)
async def monitor(description: str, timeout_ms: int = 300000, persistent: bool = False, command: str = "") -> str:
    """Start a background monitor streaming events from a long-running script."""
    return json.dumps({"status":"started","description":description,"persistent":persistent,"timeout_ms":timeout_ms})
