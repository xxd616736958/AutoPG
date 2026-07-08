"""Project context — AUTOPG.md injection."""
import os
from .base import AgentMiddleware


class ProjectContextMiddleware(AgentMiddleware):
    async def abefore_agent(self, state: dict, context) -> dict | None:
        autopg_md = os.path.join(context.cwd, "AUTOPG.md")
        if not os.path.exists(autopg_md): return None
        try:
            with open(autopg_md, "r") as f:
                content = f.read()[:10000]
            sys = state.get("system_prompt", "")
            if "AUTOPG.md" not in sys:
                return {"system_prompt": sys + f"\n\n# Project (AUTOPG.md)\n\n{content}"}
        except Exception:
            pass
        return None
