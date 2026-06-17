"""
User hooks — Claude Code hooks system. Shell commands triggered by agent events.
Configuration: ~/.db-claude/config.json → "hooks" field.
"""
import os, json, asyncio, fnmatch
from typing import Optional


def load_hooks_config() -> dict:
    """Load hooks from ~/.db-claude/config.json."""
    config_path = os.path.join(os.path.expanduser("~/.db-claude"), "config.json")
    try:
        with open(config_path) as f:
            return json.load(f).get("hooks", {})
    except Exception:
        return {}


def _match_matcher(matcher: Optional[str], tool_name: str, tool_args: dict) -> bool:
    """Check if a matcher pattern applies. 'Bash(git *)' matches Bash with git commands."""
    if not matcher:
        return True
    if "(" in matcher:
        base = matcher.split("(")[0]
        if tool_name.lower() != base.lower():
            return False
        inner = matcher.split("(", 1)[1].rstrip(")")
        if inner == "*":
            return True
        # Match against relevant arg (command for Bash, file_path for Write)
        if tool_name.lower() == "bash" and "command" in tool_args:
            return fnmatch.fnmatch(tool_args.get("command", ""), inner)
        if "file_path" in tool_args:
            return fnmatch.fnmatch(tool_args.get("file_path", ""), inner)
        return False
    return tool_name.lower() == matcher.lower()


async def run_shell_hook(command: str, env: dict = None, timeout: float = 30.0) -> dict:
    """Execute a shell hook command. Returns {exit_code, stdout, stderr}."""
    hook_env = {**os.environ, **(env or {})}
    try:
        proc = await asyncio.wait_for(
            asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=hook_env,
            ),
            timeout=timeout,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return {
            "exit_code": proc.returncode or 0,
            "stdout": (stdout or b"").decode("utf-8", errors="replace"),
            "stderr": (stderr or b"").decode("utf-8", errors="replace"),
        }
    except asyncio.TimeoutError:
        return {"exit_code": -1, "stdout": "", "stderr": f"Hook timed out after {timeout}s"}
    except Exception as e:
        return {"exit_code": -1, "stdout": "", "stderr": str(e)}


def build_hook_env(tool_name: str, tool_args: dict) -> dict:
    """Build environment variables for hook execution (Claude Code match)."""
    env = {
        "CLAUDE_TOOL_NAME": tool_name,
        "CLAUDE_TOOL_INPUT": json.dumps(tool_args),
    }
    if "file_path" in tool_args:
        env["CLAUDE_FILE_PATH"] = tool_args["file_path"]
    if "command" in tool_args:
        env["CLAUDE_COMMAND"] = tool_args["command"]
    return env


async def execute_matching_hooks(
    event: str, tool_name: str, tool_args: dict, hooks_config: dict
) -> Optional[str]:
    """Run matching hooks for an event. Returns blocking message if any hook blocks."""
    for hook in hooks_config.get(event, []):
        matcher = hook.get("matcher")
        if not _match_matcher(matcher, tool_name, tool_args):
            continue
        env = build_hook_env(tool_name, tool_args)
        result = await run_shell_hook(hook["command"], env)
        if result["exit_code"] == 2:
            return result["stderr"].strip() or f"Blocked by {event} hook"
    return None
