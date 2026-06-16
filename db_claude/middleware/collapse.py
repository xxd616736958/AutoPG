"""Context collapse before each model call."""
from .base import AgentMiddleware


class ContextCollapseMiddleware(AgentMiddleware):
    """Runs projectView before every LLM call, replacing collapsed spans with summaries."""

    async def abefore_model(self, state: dict, runtime: dict) -> dict | None:
        collapse_mgr = runtime.get("collapse_manager")
        if not collapse_mgr or not collapse_mgr.is_enabled():
            return None

        messages = list(state.get("messages", []))
        if len(messages) <= 20:
            return None

        turn = state.get("turn_count", 0)
        result = await collapse_mgr.apply_collapses_if_needed(messages, turn)

        if result.get("changed"):
            return {"messages": result["messages"]}
        return None
