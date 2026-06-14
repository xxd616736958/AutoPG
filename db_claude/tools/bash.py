"""
Bash tool for db-claude.
Architecturally identical to Claude Code's BashTool.
"""
import os
import subprocess
import asyncio
import shlex
from typing import Type
from pydantic import BaseModel, Field

from .base import Tool, PermissionResult, ValidationResult


class BashInput(BaseModel):
    """Input schema for Bash tool."""
    command: str = Field(description="The bash command to execute")
    description: str = Field(default="", description="Clear, concise description of what this command does")
    timeout: int = Field(default=120000, description="Optional timeout in milliseconds (max 600000)")
    run_in_background: bool = Field(default=False, description="Run command in background and notify on completion")
    dangerously_disable_sandbox: bool = Field(default=False, description="Dangerously disable sandbox mode")


class BashTool(Tool):
    """Execute bash commands in the user's environment."""

    name = "Bash"
    aliases = []
    search_hint = "execute shell commands in the user's environment"

    def input_schema(self) -> Type[BaseModel]:
        return BashInput

    async def call(self, args: dict, context: dict) -> dict:
        """Execute a bash command."""
        command = args.get("command", "")
        timeout_ms = min(args.get("timeout", 120000), 600000)
        run_in_background = args.get("run_in_background", False)
        description = args.get("description", command[:80])

        timeout_sec = timeout_ms / 1000.0
        cwd = context.get("cwd") or os.getcwd()

        try:
            if run_in_background:
                # Run in background
                process = await asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=cwd,
                )
                return {
                    "data": {
                        "status": "started",
                        "pid": process.pid,
                        "description": description,
                    },
                }

            # Run synchronously with timeout
            process = await asyncio.wait_for(
                asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=cwd,
                ),
                timeout=timeout_sec,
            )

            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout_sec,
            )

            stdout_str = stdout.decode("utf-8", errors="replace") if stdout else ""
            stderr_str = stderr.decode("utf-8", errors="replace") if stderr else ""

            # Truncate very long output
            max_output = 100000
            if len(stdout_str) > max_output:
                stdout_str = stdout_str[:max_output] + f"\n... [truncated, {len(stdout_str) - max_output} more chars]"
            if len(stderr_str) > max_output:
                stderr_str = stderr_str[:max_output] + f"\n... [truncated, {len(stderr_str) - max_output} more chars]"

            return {
                "data": {
                    "exit_code": process.returncode,
                    "stdout": stdout_str,
                    "stderr": stderr_str,
                },
            }
        except asyncio.TimeoutError:
            return {
                "data": {
                    "exit_code": -1,
                    "stdout": "",
                    "stderr": f"Command timed out after {timeout_ms}ms",
                },
            }
        except Exception as e:
            return {
                "data": {
                    "exit_code": -1,
                    "stdout": "",
                    "stderr": str(e),
                },
            }

    async def description(self, input_schema: dict, options: dict) -> str:
        return "Execute a bash command in the user's shell environment. Use for running build commands, tests, git operations, and other CLI tools. Prefer dedicated tools (Read, Glob, Grep) for file operations."

    def is_read_only(self, input_data: dict = None) -> bool:
        if not input_data:
            return False
        cmd = input_data.get("command", "").strip()
        # Heuristic: commands starting with read-only utilities
        readonly_prefixes = ("ls ", "cat ", "head ", "tail ", "grep ", "find ", "wc ", "du ", "df ", "file ", "echo ", "which ", "type ", "git log", "git diff", "git show", "git status", "pwd", "env", "printenv", "whoami", "date", "uname")
        return any(cmd.startswith(p) for p in readonly_prefixes)

    def is_destructive(self, input_data: dict = None) -> bool:
        if not input_data:
            return False
        cmd = input_data.get("command", "").strip()
        destructive_patterns = ("rm ", "rmdir ", "dd ", "mkfs.", ":(){ :|:& };:", ">", "chmod", "chown", "kill ", "pkill ")
        return any(p in cmd for p in destructive_patterns)

    def interrupt_behavior(self) -> str:
        return "cancel"

    async def check_permissions(self, input_data: dict, context: dict) -> PermissionResult:
        is_destructive = self.is_destructive(input_data)
        if is_destructive:
            return PermissionResult(behavior="ask", updated_input=input_data)
        return PermissionResult(behavior="allow", updated_input=input_data)

    def is_search_or_read_command(self, input_data: dict = None) -> dict:
        if not input_data:
            return {"is_search": False, "is_read": False, "is_list": False}
        cmd = input_data.get("command", "")
        return {
            "is_search": any(p in cmd for p in ("grep ", "find ", "rg ")),
            "is_read": any(p in cmd for p in ("cat ", "head ", "tail ", "less ")),
            "is_list": any(p in cmd for p in ("ls ", "tree ", "du ")),
        }

    def get_activity_description(self, input_data: dict = None) -> str:
        if not input_data:
            return "Running bash command"
        desc = input_data.get("description", "")
        return desc or f"Running `{input_data.get('command', '')[:60]}`"

    def to_auto_classifier_input(self, input_data: dict) -> str:
        return input_data.get("command", "")
