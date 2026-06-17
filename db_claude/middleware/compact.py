"""Auto-compact before model call — check token threshold, trigger compression."""
from .base import AgentMiddleware


class AutoCompactMiddleware(AgentMiddleware):
    """Checks token count before model call; triggers compact if exceeding threshold."""

    async def abefore_model(self, state: dict, runtime: dict) -> dict | None:
        compact_mgr = context.compact_manager
        if not compact_mgr:
            return None

        messages = list(state.get("messages", []))
        cs = compact_mgr.should_compact(messages)

        if cs["is_at_blocking"]:
            compacted = await compact_mgr.compact_messages(messages, keep_recent=15)
            return {"messages": compacted}
        return None
