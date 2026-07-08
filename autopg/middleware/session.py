"""Session persistence."""
from .base import AgentMiddleware
from ..utils.session import save_session


class SessionPersistenceMiddleware(AgentMiddleware):
    async def aafter_agent(self, state: dict, context) -> dict | None:
        if context.auto_save and context.session_id and state.get("messages"):
            save_session(context.session_id, state["messages"], metadata={
                "model": context.model, "provider": context.provider,
                "cwd": context.cwd, "usage": context.total_usage,
            })
        return None
