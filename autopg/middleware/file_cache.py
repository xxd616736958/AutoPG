"""File read cache middleware."""
from .base import AgentMiddleware


class FileCacheMiddleware(AgentMiddleware):
    """File cache is accessed via context.file_cache in execute_tools node."""
    async def awrap_tool_call(self, state: dict, context, handler):
        return await handler(state)
