"""Session persistence — save transcript on agent end."""
from .base import AgentMiddleware
from ..utils.session import save_session


class SessionPersistenceMiddleware(AgentMiddleware):
    """After agent completes, save transcript to JSONL."""

    async def aafter_agent(self, state: dict, runtime: dict) -> dict | None:
        session_id = runtime.get("session_id")
        messages = list(state.get("messages", []))
        auto_save = runtime.get("auto_save", True)

        if auto_save and session_id and messages:
            save_session(
                session_id, messages,
                metadata={
                    "model": runtime.get("model", ""),
                    "provider": runtime.get("provider", ""),
                    "cwd": runtime.get("cwd", ""),
                    "usage": runtime.get("total_usage", {}),
                },
            )
        return None
