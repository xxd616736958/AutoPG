"""
Base Tool class for db-claude with ToolNode compatibility adapter.
"""
import os, json
from abc import ABC, abstractmethod
from typing import Any, Optional, Type
from pydantic import BaseModel
from langchain_core.tools import StructuredTool


class Tool(ABC):
    """Base tool matching Claude Code's Tool type. 28 tools inherit this."""

    name: str = ""
    aliases: list[str] = []
    search_hint: str = ""
    max_result_chars: float = 50_000

    @abstractmethod
    def input_schema(self) -> Type[BaseModel]: ...

    @abstractmethod
    async def call(self, args: dict, context: dict) -> dict: ...

    @abstractmethod
    async def description(self, input_schema: dict = None, options: dict = None) -> str: ...

    def format_call(self, args: dict) -> str:
        return self.name

    def format_result(self, data: Any) -> str:
        if isinstance(data, dict):
            if "status" in data: return data["status"]
            if "count" in data: return f"{data['count']} results"
            s = str(data); return s[:200] + ("..." if len(s) > 200 else "")
        s = str(data); return s[:200] + ("..." if len(s) > 200 else "")

    def is_enabled(self) -> bool: return True
    def is_read_only(self, input_data: dict = None) -> bool: return False
    def is_destructive(self, input_data: dict = None) -> bool: return False
    def get_activity_description(self, input_data: dict = None) -> Optional[str]: return None
    def is_search_or_read_command(self, input_data: dict = None) -> dict:
        return {"is_search": False, "is_read": False, "is_list": False}

    def get_input_schema_dict(self) -> dict:
        return self.input_schema().model_json_schema()

    def to_langchain_tool(self) -> StructuredTool:
        """Convert to LangChain StructuredTool for ToolNode compatibility."""
        async def _arun(**kwargs):
            result = await self.call(kwargs, {})
            if isinstance(result, dict):
                data = result.get("data", result)
                return json.dumps(data, ensure_ascii=False, indent=2) if not isinstance(data, str) else data
            return str(result)
        return StructuredTool(
            name=self.name, description=self.search_hint or self.name,
            args_schema=self.input_schema(), coroutine=_arun,
        )


class ValidationResult:
    def __init__(self, is_valid, message="", error_code=0):
        self.is_valid=is_valid; self.message=message; self.error_code=error_code

class PermissionResult:
    def __init__(self, behavior, updated_input=None, message=""):
        self.behavior=behavior; self.updated_input=updated_input; self.message=message

class ToolRegistry:
    def __init__(self, tools=None):
        self._tools = {}; self._alias_map = {}
        if tools: [self.register(t) for t in tools]
    def register(self, tool):
        self._tools[tool.name] = tool
        for a in (tool.aliases or []): self._alias_map[a] = tool.name
    def get(self, name):
        return self._tools.get(name) or self._tools.get(self._alias_map.get(name, ""))
    def find_by_name(self, name): return self.get(name)
    def list_enabled(self): return list(self._tools.values())
    def all(self): return list(self._tools.values())
    def __iter__(self): return iter(self._tools.values())
    def __len__(self): return len(self._tools)
    def __contains__(self, name): return name in self._tools or name in self._alias_map
