"""
Base Tool class for db-claude — Claude Code format support.
"""
import os
from abc import ABC, abstractmethod
from typing import Any, Optional, Type
from pydantic import BaseModel


class Tool(ABC):
    """Base Tool matching Claude Code's Tool type."""

    name: str = ""
    aliases: list[str] = []
    search_hint: str = ""

    @abstractmethod
    def input_schema(self) -> Type[BaseModel]: ...

    @abstractmethod
    async def call(self, args: dict, context: dict) -> dict: ...

    @abstractmethod
    async def description(self, input_schema: dict, options: dict) -> str: ...

    # ── Claude Code format methods ──

    def format_call(self, args: dict) -> str:
        """One-line call format: ⏺ ToolName(key args). Must match Claude Code style.
        Override in each tool for precise formatting."""
        return self.name

    def format_result(self, data: Any) -> str:
        """Result format: ⎿ summary. Appears below the call line.
        Override in each tool for precise formatting."""
        if isinstance(data, dict):
            # Common patterns: status, count, file_path
            if "status" in data:
                return data["status"]
            if "count" in data:
                return f"{data['count']} results"
            if "file_path" in data:
                return f"{data['file_path']}"
            # Truncate dict
            s = str(data)
            return s[:200] + ("..." if len(s) > 200 else "")
        s = str(data)
        return s[:200] + ("..." if len(s) > 200 else "")

    # ── Standard methods ──

    def is_enabled(self) -> bool: return True
    def is_concurrency_safe(self, input_data: dict = None) -> bool: return False
    def is_read_only(self, input_data: dict = None) -> bool: return False
    def is_destructive(self, input_data: dict = None) -> bool: return False

    async def check_permissions(self, input_data: dict, context: dict):
        from .base import PermissionResult
        return PermissionResult(behavior="allow", updated_input=input_data)

    async def validate_input(self, input_data: dict, context: dict):
        from .base import ValidationResult
        try:
            self.input_schema()(**input_data)
            return ValidationResult(is_valid=True)
        except Exception as e:
            return ValidationResult(is_valid=False, message=str(e), error_code=1)

    def user_facing_name(self, input_data: dict = None) -> str: return self.name
    def get_activity_description(self, input_data: dict = None) -> Optional[str]: return None
    def interrupt_behavior(self) -> str: return "block"
    def is_search_or_read_command(self, input_data: dict = None) -> dict:
        return {"is_search": False, "is_read": False, "is_list": False}

    def get_input_schema_dict(self) -> dict:
        return self.input_schema().model_json_schema()

    def get_langchain_tool(self):
        from langchain_core.tools import StructuredTool
        async def _call(**kwargs):
            result = await self.call(kwargs, {})
            return result.get("data", result) if isinstance(result, dict) else result
        return StructuredTool(
            name=self.name, description=self.search_hint or self.name,
            args_schema=self.input_schema(), func=_call,
        )


class ValidationResult:
    def __init__(self, is_valid: bool, message: str = "", error_code: int = 0):
        self.is_valid = is_valid; self.message = message; self.error_code = error_code


class PermissionResult:
    def __init__(self, behavior: str, updated_input: dict = None, message: str = ""):
        self.behavior = behavior; self.updated_input = updated_input; self.message = message


class ToolRegistry:
    def __init__(self, tools: list[Tool] = None):
        self._tools: dict[str, Tool] = {}; self._alias_map: dict[str, str] = {}
        if tools:
            for t in tools: self.register(t)

    def register(self, tool: Tool):
        self._tools[tool.name] = tool
        for alias in (tool.aliases or []): self._alias_map[alias] = tool.name

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name) or self._tools.get(self._alias_map.get(name, ""))

    def find_by_name(self, name: str) -> Optional[Tool]: return self.get(name)
    def list_enabled(self) -> list[Tool]: return [t for t in self._tools.values() if t.is_enabled()]
    def all(self) -> list[Tool]: return list(self._tools.values())
    def __iter__(self): return iter(self._tools.values())
    def __len__(self): return len(self._tools)
    def __contains__(self, name: str): return name in self._tools or name in self._alias_map
