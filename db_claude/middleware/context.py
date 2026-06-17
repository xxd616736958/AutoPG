"""Project context — CLAUDE.md injection."""
import os
from .base import AgentMiddleware


class ProjectContextMiddleware(AgentMiddleware):
    async def abefore_agent(self, state: dict, context) -> dict | None:
        claude_md = os.path.join(context.cwd, "CLAUDE.md")
        if not os.path.exists(claude_md): return None
        try:
            with open(claude_md, "r") as f:
                content = f.read()[:10000]
            sys = state.get("system_prompt", "")
            if "CLAUDE.md" not in sys:
                return {"system_prompt": sys + f"\n\n# Project (CLAUDE.md)\n\n{content}"}
        except Exception:
            pass
        return None
