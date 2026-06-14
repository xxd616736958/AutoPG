"""
Tools module for db-claude.
All tool classes matching Claude Code's tool system architecture.
"""
from .base import Tool, ToolRegistry, PermissionResult, ValidationResult
from .bash import BashTool
from .file_read import FileReadTool
from .file_write import FileWriteTool
from .file_edit import FileEditTool
from .glob import GlobTool
from .grep import GrepTool
from .task import (
    TaskCreateTool,
    TaskUpdateTool,
    TaskListTool,
    TaskGetTool,
    TaskStopTool,
    TaskOutputTool,
)
from .web_search import WebSearchTool, WebFetchTool
from .todo_write import TodoWriteTool
from .notebook_edit import NotebookEditTool
from .ask_user import AskUserQuestionTool
from .plan_mode import (
    EnterPlanModeTool,
    ExitPlanModeTool,
    EnterWorktreeTool,
    ExitWorktreeTool,
)
from .cron import CronCreateTool, CronDeleteTool, CronListTool
from .agent_tool import AgentTool
from .skill import SkillTool
from .workflow import WorkflowTool
from .monitor import MonitorTool


def create_default_tools() -> ToolRegistry:
    """
    Create the default tool set matching Claude Code's built-in tool set.
    This is the Python equivalent of how tools are assembled in Claude Code's
    CLI initialization.
    """
    registry = ToolRegistry()

    # File tools
    registry.register(FileReadTool())
    registry.register(FileWriteTool())
    registry.register(FileEditTool())
    registry.register(GlobTool())
    registry.register(GrepTool())

    # Shell
    registry.register(BashTool())

    # Task management
    registry.register(TaskCreateTool())
    registry.register(TaskUpdateTool())
    registry.register(TaskListTool())
    registry.register(TaskGetTool())
    registry.register(TaskStopTool())
    registry.register(TaskOutputTool())
    registry.register(TodoWriteTool())

    # Web tools
    registry.register(WebSearchTool())
    registry.register(WebFetchTool())

    # User interaction
    registry.register(AskUserQuestionTool())

    # Plan mode
    registry.register(EnterPlanModeTool())
    registry.register(ExitPlanModeTool())

    # Worktree
    registry.register(EnterWorktreeTool())
    registry.register(ExitWorktreeTool())

    # Notebook
    registry.register(NotebookEditTool())

    # Cron
    registry.register(CronCreateTool())
    registry.register(CronDeleteTool())
    registry.register(CronListTool())

    # Orchestration
    registry.register(AgentTool())
    registry.register(SkillTool())
    registry.register(WorkflowTool())

    # Monitor
    registry.register(MonitorTool())

    return registry


__all__ = [
    "Tool",
    "ToolRegistry",
    "PermissionResult",
    "ValidationResult",
    "create_default_tools",
    # Individual tools
    "BashTool",
    "FileReadTool",
    "FileWriteTool",
    "FileEditTool",
    "GlobTool",
    "GrepTool",
    "TaskCreateTool",
    "TaskUpdateTool",
    "TaskListTool",
    "TaskGetTool",
    "TaskStopTool",
    "TaskOutputTool",
    "TodoWriteTool",
    "WebSearchTool",
    "WebFetchTool",
    "AskUserQuestionTool",
    "EnterPlanModeTool",
    "ExitPlanModeTool",
    "EnterWorktreeTool",
    "ExitWorktreeTool",
    "NotebookEditTool",
    "CronCreateTool",
    "CronDeleteTool",
    "CronListTool",
    "AgentTool",
    "SkillTool",
    "WorkflowTool",
    "MonitorTool",
]
