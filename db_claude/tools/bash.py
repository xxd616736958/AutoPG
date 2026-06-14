"""Bash tool — Claude Code format."""
import os, subprocess, asyncio, shlex
from typing import Type, Any
from pydantic import BaseModel, Field
from .base import Tool, PermissionResult

class BashInput(BaseModel):
    command: str = Field(description="The bash command to execute")
    description: str = Field(default="", description="Clear description of what this command does")
    timeout: int = Field(default=120000, description="Timeout in ms (max 600000)")
    run_in_background: bool = Field(default=False, description="Run in background")
    dangerously_disable_sandbox: bool = Field(default=False, description="Disable sandbox")

class BashTool(Tool):
    name = "Bash"; aliases = []; search_hint = "execute shell commands"

    def input_schema(self) -> Type[BaseModel]: return BashInput

    def format_call(self, args: dict) -> str:
        cmd = args.get("command", "")
        desc = args.get("description", "")
        # Claude Code format: Bash(ls -la)
        display = cmd[:80] + ("..." if len(cmd) > 80 else "")
        return f"Bash({display})"

    def format_result(self, data: Any) -> str:
        if not isinstance(data, dict): return str(data)[:200]
        exit_code = data.get("exit_code", -1)
        stdout = data.get("stdout", "")
        stderr = data.get("stderr", "")
        # Show stderr if present, else first line of stdout
        if stderr:
            lines = stderr.strip().split("\n")
            return lines[0][:120] if lines else f"exit={exit_code}"
        lines = stdout.strip().split("\n") if stdout else []
        if not lines: return f"exit={exit_code}"
        # Multiple lines → show count, single line → show it
        if len(lines) <= 3:
            return "\n".join(line[:100] for line in lines)
        return f"{len(lines)} lines of output"

    async def call(self, args: dict, context: dict) -> dict:
        command = args.get("command", "")
        timeout_ms = min(args.get("timeout", 120000), 600000)
        run_in_background = args.get("run_in_background", False)
        timeout_sec = timeout_ms / 1000.0
        cwd = context.get("cwd") or os.getcwd()

        try:
            if run_in_background:
                process = await asyncio.create_subprocess_shell(command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, cwd=cwd)
                return {"data": {"status": "started", "pid": process.pid, "description": args.get("description", command[:80])}}

            process = await asyncio.wait_for(asyncio.create_subprocess_shell(command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, cwd=cwd), timeout=timeout_sec)
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_sec)
            stdout_str, stderr_str = (stdout or b"").decode("utf-8", errors="replace"), (stderr or b"").decode("utf-8", errors="replace")
            max_out = 100000
            if len(stdout_str) > max_out: stdout_str = stdout_str[:max_out] + f"\n... [{len(stdout_str) - max_out} more chars]"
            if len(stderr_str) > max_out: stderr_str = stderr_str[:max_out] + f"\n... [{len(stderr_str) - max_out} more chars]"
            return {"data": {"exit_code": process.returncode, "stdout": stdout_str, "stderr": stderr_str}}
        except asyncio.TimeoutError:
            return {"data": {"exit_code": -1, "stdout": "", "stderr": f"Command timed out after {timeout_ms}ms"}}
        except Exception as e:
            return {"data": {"exit_code": -1, "stdout": "", "stderr": str(e)}}

    async def description(self, input_schema: dict, options: dict) -> str:
        return "Execute a bash command in the user's shell environment."

    def is_read_only(self, input_data: dict = None) -> bool:
        if not input_data: return False
        cmd = input_data.get("command", "").strip()
        ro = ("ls ", "cat ", "head ", "tail ", "grep ", "find ", "wc ", "du ", "df ", "file ", "echo ", "which ", "type ", "git log", "git diff", "git show", "git status", "pwd", "env", "printenv", "whoami", "date", "uname")
        return any(cmd.startswith(p) for p in ro)

    def is_destructive(self, input_data: dict = None) -> bool:
        if not input_data: return False
        cmd = input_data.get("command", "").strip()
        return any(p in cmd for p in ("rm ", "rmdir ", "dd ", "mkfs.", ">", "chmod", "chown", "kill ", "pkill "))

    def interrupt_behavior(self) -> str: return "cancel"

    async def check_permissions(self, input_data: dict, context: dict) -> PermissionResult:
        return PermissionResult(behavior="ask" if self.is_destructive(input_data) else "allow", updated_input=input_data)

    def get_activity_description(self, input_data: dict = None) -> str:
        if not input_data: return "Running bash"
        desc = input_data.get("description", "")
        return desc or f"Running `{input_data.get('command', '')[:60]}`"

    def is_search_or_read_command(self, input_data: dict = None) -> dict:
        if not input_data: return {"is_search": False, "is_read": False, "is_list": False}
        cmd = input_data.get("command", "")
        return {"is_search": any(p in cmd for p in ("grep ", "find ", "rg ")), "is_read": any(p in cmd for p in ("cat ", "head ", "tail ")), "is_list": any(p in cmd for p in ("ls ", "tree ", "du "))}
