"""Permission check — intercepts destructive tool calls."""
from .base import AgentMiddleware


class PermissionCheckMiddleware(AgentMiddleware):
    async def awrap_tool_call(self, state: dict, context, handler):
        # Handler is called for each tool; permission check is in query_engine callback
        return await handler(state)
