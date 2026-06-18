"""
User hooks — Claude Code hooks system. Shell commands triggered by agent events.
Configuration: ~/.db-claude/config.json → "hooks" field.
"""
import os, json, asyncio, fnmatch, logging, time
from typing import Optional

logger = logging.getLogger(__name__)
hook_logger = logging.getLogger("db_claude.hooks")  # Separate file for audit


def load_hooks_config() -> dict:
    """Load hooks from ~/.db-claude/config.json."""
    config_path = os.path.join(os.path.expanduser("~/.db-claude"), "config.json")
    try:
        with open(config_path) as f:
            hooks = json.load(f).get("hooks", {})
        logger.info("hooks_loaded events=%s count=%d", list(hooks.keys()), sum(len(v) for v in hooks.values()))
        return hooks
    except Exception:
        logger.debug("hooks_config_not_found path=%s", config_path)
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
            fname = os.path.basename(tool_args.get("file_path", ""))
            return fnmatch.fnmatch(fname, inner)
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
    """Run matching hooks. Returns combined stdout for display, or blocking message."""
    all_output = []
    for hook in hooks_config.get(event, []):
        matcher = hook.get("matcher")
        if not _match_matcher(matcher, tool_name, tool_args):
            continue
        env = build_hook_env(tool_name, tool_args)
        t0 = time.time()
        result = await run_shell_hook(hook["command"], env)
        elapsed = int((time.time() - t0) * 1000)
        hook_logger.info("hook_exec event=%s tool=%s matcher=%s exit=%d stdout_len=%d stderr_len=%d duration_ms=%d",
                         event, tool_name, matcher or "*", result["exit_code"],
                         len(result["stdout"]), len(result["stderr"]), elapsed)
        if result["exit_code"] == 2:
            hook_logger.warning("hook_blocked event=%s tool=%s reason=%s", event, tool_name, result["stderr"][:200])
            return result["stderr"].strip() or f"Blocked by {event} hook"
        if result["stdout"].strip():
            all_output.append(result["stdout"].strip())
    return "\n".join(all_output) if all_output else None
