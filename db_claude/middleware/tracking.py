"""Token tracking — count tokens after each model call."""
from .base import AgentMiddleware


class TokenTrackingMiddleware(AgentMiddleware):
    """After model call, update token usage counts."""

    async def aafter_model(self, state: dict, runtime: dict) -> dict | None:
        response = runtime.get("_last_model_response")
        total_usage = runtime.get("total_usage", {})

        if response:
            if hasattr(response, "usage_metadata") and response.usage_metadata:
                um = response.usage_metadata
                total_usage["input_tokens"] = total_usage.get("input_tokens", 0) + um.get("input_tokens", 0)
                total_usage["output_tokens"] = total_usage.get("output_tokens", 0) + um.get("output_tokens", 0)
            elif hasattr(response, "response_metadata") and response.response_metadata:
                rm = response.response_metadata
                tu = rm.get("token_usage", {})
                total_usage["input_tokens"] = total_usage.get("input_tokens", 0) + tu.get("prompt_tokens", 0)
                total_usage["output_tokens"] = total_usage.get("output_tokens", 0) + tu.get("completion_tokens", 0)
            runtime["total_usage"] = total_usage

        return None
