"""
Permission system for AutoPG.
Architecturally mirrors AutoPG's permission system (src/utils/permissions/).
"""
from enum import Enum
from typing import Optional, Any
from dataclasses import dataclass, field


class PermissionMode(str, Enum):
    """Permission modes matching AutoPG's PermissionMode."""
    DEFAULT = "default"
    ACCEPT_EDITS = "accept_edits"
    BYPASS = "bypass"
    PLAN = "plan"


class Decision(str, Enum):
    """Permission decisions."""
    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"


@dataclass
class PermissionResult:
    """Result of a permission check."""
    behavior: Decision
    updated_input: Optional[dict] = None
    message: str = ""

    @property
    def is_allowed(self) -> bool:
        return self.behavior == Decision.ALLOW

    @property
    def is_denied(self) -> bool:
        return self.behavior == Decision.DENY


@dataclass
class ToolPermissionContext:
    """Permission context for tool execution."""
    mode: PermissionMode = PermissionMode.DEFAULT
    additional_working_directories: set = field(default_factory=set)
    always_allow_rules: dict = field(default_factory=dict)
    always_deny_rules: dict = field(default_factory=dict)
    always_ask_rules: dict = field(default_factory=dict)
    is_bypass_permissions_mode_available: bool = False
    should_avoid_permission_prompts: bool = False

    def check_tool_permission(
        self,
        tool_name: str,
        tool_input: dict,
        is_read_only: bool = False,
        is_destructive: bool = False,
    ) -> PermissionResult:
        """
        Check if a tool should be allowed based on current permission context.
        Mirrors the permission resolution logic in AutoPG.
        """
        # Bypass mode: allow everything
        if self.mode == PermissionMode.BYPASS:
            return PermissionResult(behavior=Decision.ALLOW, updated_input=tool_input)

        # Check always-deny rules first
        for rule_pattern, rule in self.always_deny_rules.items():
            if self._match_rule(tool_name, rule_pattern):
                return PermissionResult(
                    behavior=Decision.DENY,
                    message=f"Denied by rule: {rule_pattern}",
                )

        # Check always-allow rules
        for rule_pattern, rule in self.always_allow_rules.items():
            if self._match_rule(tool_name, rule_pattern):
                return PermissionResult(behavior=Decision.ALLOW, updated_input=tool_input)

        # Read-only tools in accept_edits mode: auto-allow
        if self.mode == PermissionMode.ACCEPT_EDITS and is_read_only:
            return PermissionResult(behavior=Decision.ALLOW, updated_input=tool_input)

        # Plan mode: allow read-only, ask for writes
        if self.mode == PermissionMode.PLAN:
            if is_read_only:
                return PermissionResult(behavior=Decision.ALLOW, updated_input=tool_input)
            return PermissionResult(
                behavior=Decision.ASK,
                updated_input=tool_input,
                message="Plan mode: write operations require approval",
            )

        # Default mode: ask for destructive, allow reads
        if is_destructive:
            return PermissionResult(
                behavior=Decision.ASK,
                updated_input=tool_input,
                message=f"Destructive operation '{tool_name}' requires approval",
            )

        # Allow non-destructive operations
        return PermissionResult(behavior=Decision.ALLOW, updated_input=tool_input)

    def _match_rule(self, tool_name: str, rule_pattern: str) -> bool:
        """Match a tool name against a permission rule pattern."""
        # Exact match
        if tool_name == rule_pattern:
            return True
        # Wildcard pattern like "Bash(git *)"
        if "(" in rule_pattern:
            base = rule_pattern.split("(")[0]
            return tool_name == base
        return False
