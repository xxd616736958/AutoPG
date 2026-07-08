"""Middleware for AutoPG."""
from .base import AgentMiddleware, MiddlewareStack
from .collapse import ContextCollapseMiddleware
from .compact import AutoCompactMiddleware
from .permissions import PermissionCheckMiddleware
from .tool_budget import ToolResultBudgetMiddleware
from .file_cache import FileCacheMiddleware
from .session import SessionPersistenceMiddleware
from .context import ProjectContextMiddleware
from .tracking import TokenTrackingMiddleware
from .user_hooks import UserHookMiddleware

__all__ = [
    "AgentMiddleware", "MiddlewareStack",
    "ContextCollapseMiddleware", "AutoCompactMiddleware",
    "PermissionCheckMiddleware", "ToolResultBudgetMiddleware",
    "FileCacheMiddleware", "SessionPersistenceMiddleware",
    "ProjectContextMiddleware", "TokenTrackingMiddleware",
    "UserHookMiddleware",
]
