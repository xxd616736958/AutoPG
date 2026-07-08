"""Monitor tool."""
import json
from pydantic import Field
from langchain_core.tools import tool

@tool
async def monitor(
    description: str = Field(description="Short human-readable description of what you are monitoring"),
    command: str = Field(description="Shell command or script; each stdout line is an event, exit ends the watch"),
    timeout_ms: int = Field(default=300000, ge=1000, le=3600000, description="Kill the monitor after this deadline in milliseconds"),
    persistent: bool = Field(default=False, description="Run for the lifetime of the session with no timeout"),
) -> str:
    """Start a background monitor that streams events from a long-running script."""
    return json.dumps({"status":"started","description":description,"persistent":persistent,"timeout_ms":timeout_ms})
