"""File read cache — return cached content for repeated reads."""
from .base import AgentMiddleware


class FileCacheMiddleware(AgentMiddleware):
    """Wraps Read tool calls — checks cache, stores results."""

    async def awrap_tool_call(self, request: dict, handler) -> str:
        if request.get("tool_name") != "Read":
            return await handler(request)

        file_cache = request.get("file_cache")
        file_path = request.get("tool_args", {}).get("file_path", "")
        offset = request.get("tool_args", {}).get("offset", 0)
        limit = request.get("tool_args", {}).get("limit")

        # Only cache full-file reads
        if file_cache and file_path and offset == 0 and limit is None:
            cached = file_cache.get(file_path)
            if cached:
                return cached

            result = await handler(request)

            if isinstance(result, str) and len(result) < 100_000:
                file_cache.set(file_path, result)
            return result

        return await handler(request)
