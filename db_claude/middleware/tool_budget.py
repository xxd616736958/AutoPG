"""Tool result budget — save oversized results to disk, return preview."""
import os, json
from .base import AgentMiddleware


class ToolResultBudgetMiddleware(AgentMiddleware):
    """Wraps tool calls — checks result size, saves large results to temp dir."""

    async def awrap_tool_call(self, request: dict, handler) -> str:
        result = await handler(request)

        max_chars = request.get("max_result_chars", 50_000)
        temp_dir = request.get("result_temp_dir", "")

        if isinstance(result, str) and len(result) > max_chars and max_chars != float("inf"):
            if temp_dir:
                os.makedirs(temp_dir, exist_ok=True)
                result_id = request.get("tool_call_id", "unknown")[:12]
                result_file = os.path.join(temp_dir, f"result_{result_id}.txt")
                try:
                    with open(result_file, "w", encoding="utf-8") as f:
                        f.write(result)
                    return (
                        f"[Tool result too large ({len(result):,} chars > {max_chars:,} limit). "
                        f"Full content saved to {result_file}. Preview:\n"
                        f"{result[:500]}...\nUse Read to access the full result."
                    )
                except Exception:
                    pass
            return result[:max_chars] + f"\n...[truncated at {max_chars} chars]"

        return result
