"""
Base Tool class for db-claude.
Architecturally identical to Claude Code's Tool type (src/Tool.ts).
"""
from abc import ABC, abstractmethod
from typing import Any, Optional, Callable, Type, get_type_hints
from pydantic import BaseModel


class ValidationResult:
    """Result of tool input validation."""
    def __init__(self, is_valid: bool, message: str = "", error_code: int = 0):
        self.is_valid = is_valid
        self.message = message
        self.error_code = error_code


class PermissionResult:
    """Result of tool permission check."""
    def __init__(
        self,
        behavior: str,  # 'allow', 'deny', 'ask'
        updated_input: Optional[dict] = None,
        message: str = "",
    ):
        self.behavior = behavior
        self.updated_input = updated_input
        self.message = message


class Tool(ABC):
    """
    Base Tool class matching Claude Code's Tool type signature.

    Each tool has:
    - name: unique identifier
    - aliases: alternative names for backward compatibility
    - search_hint: one-line capability phrase for keyword matching
    - input_schema: Pydantic model for input validation
    - description(): async, returns tool description for system prompt
    - call(): executes the tool
    - Various permission and lifecycle methods
    """

    # Core identity
    name: str = ""
    aliases: list[str] = []
    search_hint: str = ""

    def __init__(self):
        pass

    # -- Abstract / must-implement --

    @abstractmethod
    def input_schema(self) -> Type[BaseModel]:
        """Return the Pydantic model for input validation."""
        ...

    @abstractmethod
    async def call(
        self,
        args: dict,
        context: dict,  # ToolUseContext
    ) -> dict:
        """
        Execute the tool. Returns a dict with:
        - data: the result data
        - new_messages: optional list of messages to inject
        - context_modifier: optional function to modify context
        """
        ...

    @abstractmethod
    async def description(
        self,
        input_schema: dict,
        options: dict,
    ) -> str:
        """Return the tool description for the system prompt."""
        ...

    # -- Defaultable methods (mirrors TOOL_DEFAULTS) --

    def is_enabled(self) -> bool:
        """Whether this tool is currently enabled."""
        return True

    def is_concurrency_safe(self, input_data: dict = None) -> bool:
        """Whether this tool can run concurrently with itself."""
        return False

    def is_read_only(self, input_data: dict = None) -> bool:
        """Whether this tool only reads, never writes."""
        return False

    def is_destructive(self, input_data: dict = None) -> bool:
        """Whether this tool performs irreversible operations."""
        return False

    async def check_permissions(
        self,
        input_data: dict,
        context: dict,
    ) -> PermissionResult:
        """Check if the tool is allowed to execute with given input."""
        return PermissionResult(behavior="allow", updated_input=input_data)

    async def validate_input(
        self,
        input_data: dict,
        context: dict,
    ) -> ValidationResult:
        """Validate tool input before execution."""
        try:
            schema = self.input_schema()
            schema(**input_data)
            return ValidationResult(is_valid=True)
        except Exception as e:
            return ValidationResult(is_valid=False, message=str(e), error_code=1)

    def to_auto_classifier_input(self, input_data: dict) -> str:
        """Return compact representation for the auto-mode security classifier."""
        return ""

    def user_facing_name(self, input_data: dict = None) -> str:
        """Human-readable name for UI display."""
        return self.name

    def get_tool_use_summary(self, input_data: dict = None) -> Optional[str]:
        """Short summary for compact views."""
        return None

    def get_activity_description(self, input_data: dict = None) -> Optional[str]:
        """Present-tense activity description for spinner display."""
        return None

    def interrupt_behavior(self) -> str:
        """What happens when user submits while tool is running: 'cancel' or 'block'."""
        return "block"

    def is_search_or_read_command(self, input_data: dict = None) -> dict:
        """Whether this operation is a search/read for UI collapsing."""
        return {"is_search": False, "is_read": False, "is_list": False}

    # -- Schema helpers --

    def get_input_schema_dict(self) -> dict:
        """Get the JSON Schema representation of the input schema."""
        schema_cls = self.input_schema()
        return schema_cls.model_json_schema()

    def get_langchain_tool(self):
        """Convert to a LangChain-compatible tool representation."""
        from langchain_core.tools import StructuredTool

        async def _call(**kwargs):
            result = await self.call(kwargs, {})
            if isinstance(result, dict):
                return result.get("data", result)
            return result

        return StructuredTool(
            name=self.name,
            description=self.search_hint or self.name,
            args_schema=self.input_schema(),
            func=_call,
        )


class ToolRegistry:
    """Collection of tools, matching Claude Code's Tools type (src/Tool.ts)."""

    def __init__(self, tools: Optional[list[Tool]] = None):
        self._tools: dict[str, Tool] = {}
        self._alias_map: dict[str, str] = {}
        if tools:
            for tool in tools:
                self.register(tool)

    def register(self, tool: Tool):
        """Register a tool by name and aliases."""
        self._tools[tool.name] = tool
        for alias in tool.aliases:
            self._alias_map[alias] = tool.name

    def get(self, name: str) -> Optional[Tool]:
        """Find a tool by name or alias."""
        if name in self._tools:
            return self._tools[name]
        if name in self._alias_map:
            return self._tools[self._alias_map[name]]
        return None

    def find_by_name(self, name: str) -> Optional[Tool]:
        """Find a tool by name (matching toolMatchesName)."""
        return self.get(name)

    def list_enabled(self) -> list[Tool]:
        """List all enabled tools."""
        return [t for t in self._tools.values() if t.is_enabled()]

    def all(self) -> list[Tool]:
        """List all registered tools."""
        return list(self._tools.values())

    def __iter__(self):
        return iter(self._tools.values())

    def __len__(self):
        return len(self._tools)

    def __contains__(self, name: str):
        return name in self._tools or name in self._alias_map
