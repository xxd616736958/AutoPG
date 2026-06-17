"""Tool result budget middleware — handled in execute_tools node."""
from .base import AgentMiddleware


class ToolResultBudgetMiddleware(AgentMiddleware):
    """Budget check is in execute_tools node — this middleware provides lifecycle hook."""
    async def awrap_tool_call(self, state: dict, context, handler):
        return await handler(state)
