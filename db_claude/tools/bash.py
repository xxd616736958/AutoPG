"""Bash tool."""
import os, json, asyncio
from pydantic import BaseModel, Field
from langchain_core.tools import tool

class BashInput(BaseModel):
    command: str = Field(description="The bash command to execute", min_length=1, max_length=10000)
    description: str = Field(default="", description="Clear description of what this command does")
    timeout: int = Field(default=120000, ge=1000, le=600000, description="Timeout in ms")
    run_in_background: bool = Field(default=False, description="Run in background and notify on completion")

@tool(args_schema=BashInput)
async def bash(command: str, description: str = "", timeout: int = 120000,
               run_in_background: bool = False) -> str:
    """Execute a bash command in the user's shell environment.

    Args:
        command: The bash command to execute
        description: Clear description of what this command does
        timeout: Optional timeout in milliseconds (max 600000)
        run_in_background: Run command in background and notify on completion
    """
    timeout_sec = min(timeout, 600000) / 1000.0
    cwd = os.getcwd()
    try:
        if run_in_background:
            proc = await asyncio.create_subprocess_shell(command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, cwd=cwd)
            return json.dumps({"status": "started", "pid": proc.pid})
        proc = await asyncio.wait_for(asyncio.create_subprocess_shell(command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, cwd=cwd), timeout=timeout_sec)
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_sec)
        out = (stdout or b"").decode("utf-8", errors="replace")
        err = (stderr or b"").decode("utf-8", errors="replace")
        if len(out) > 100000: out = out[:100000] + f"\n... [{len(out)-100000} more chars]"
        if len(err) > 100000: err = err[:100000] + f"\n... [{len(err)-100000} more chars]"
        return json.dumps({"exit_code": proc.returncode, "stdout": out, "stderr": err})
    except asyncio.TimeoutError:
        return json.dumps({"exit_code": -1, "stdout": "", "stderr": f"Timed out after {timeout}ms"})
    except Exception as e:
        return json.dumps({"exit_code": -1, "stdout": "", "stderr": str(e)})
