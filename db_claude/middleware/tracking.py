"""Token tracking."""
from .base import AgentMiddleware


class TokenTrackingMiddleware(AgentMiddleware):
    async def aafter_model(self, state: dict, context) -> dict | None:
        return None  # Usage tracked in call_model node via context.total_usage
