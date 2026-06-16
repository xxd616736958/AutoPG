"""Project context — inject CLAUDE.md into system prompt."""
import os
from .base import AgentMiddleware


class ProjectContextMiddleware(AgentMiddleware):
    """Before agent starts, read CLAUDE.md and inject into state."""

    async def abefore_agent(self, state: dict, runtime: dict) -> dict | None:
        cwd = runtime.get("cwd", os.getcwd())
        claude_md_path = os.path.join(cwd, "CLAUDE.md")

        if not os.path.exists(claude_md_path):
            return None

        try:
            with open(claude_md_path, "r", encoding="utf-8") as f:
                content = f.read()
            if len(content) > 10000:
                content = content[:10000] + "\n... [CLAUDE.md truncated]"

            sys_prompt = state.get("system_prompt", "")
            if "CLAUDE.md" not in sys_prompt:
                injection = f"\n\n# Project Instructions (CLAUDE.md)\n\n{content}"
                return {"system_prompt": sys_prompt + injection}
        except Exception:
            pass
        return None
