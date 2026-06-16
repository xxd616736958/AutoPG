"""Permission check before destructive tool calls."""
from .base import AgentMiddleware


class PermissionCheckMiddleware(AgentMiddleware):
    """Wraps tool calls — asks user before destructive operations."""

    async def awrap_tool_call(self, request: dict, handler) -> dict:
        name = request.get("tool_name", "")
        args = request.get("tool_args", {})
        is_destructive = request.get("is_destructive", False)
        on_check = request.get("on_permission_check")

        if is_destructive and on_check:
            allowed = on_check(name, True, f"{name}({self._fmt_args(args)})")
            if not allowed:
                return {"content": f"Tool '{name}' denied by user.", "is_error": True}

        return await handler(request)

    @staticmethod
    def _fmt_args(args: dict) -> str:
        if "file_path" in args:
            return args["file_path"]
        if "command" in args:
            return args["command"][:40]
        return str(list(args.keys())[0]) if args else ""
