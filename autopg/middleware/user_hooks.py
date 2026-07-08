"""User hook middleware — Stop, SessionStart hooks."""
import json, os
from .base import AgentMiddleware


class UserHookMiddleware(AgentMiddleware):
    """Runs Stop hooks after model response. PreToolUse/PostToolUse handled by ToolNode."""

    def __init__(self, hooks_config: dict = None):
        self._hooks = hooks_config or {}

    async def aafter_model(self, state: dict, context) -> dict | None:
        """Run Stop hooks after model completes."""
        for hook in self._hooks.get("Stop", []):
            from ..utils.hooks import run_shell_hook
            result = await run_shell_hook(hook["command"])
            if result["stdout"].strip():
                msgs = list(state.get("messages", []))
                from langchain_core.messages import HumanMessage
                msgs.append(HumanMessage(
                    content=f"[Stop hook: {hook['command']}]\n{result['stdout']}",
                    additional_kwargs={"is_meta": True},
                ))
                return {"messages": msgs}
        return None

    async def abefore_agent(self, state: dict, context) -> dict | None:
        """Run SessionStart hooks."""
        for hook in self._hooks.get("SessionStart", []):
            from ..utils.hooks import run_shell_hook
            result = await run_shell_hook(hook.get("command", ""))
            if result["stdout"].strip():
                sys = state.get("system_prompt", "")
                return {"system_prompt": sys + "\n\n[Hook context]\n" + result["stdout"]}
        return None
