"""
Task management tools for db-claude.
Architecturally identical to Claude Code's TaskCreateTool, TaskUpdateTool, TaskListTool, TaskGetTool, TaskStopTool, TaskOutputTool.
"""
from typing import Type, Optional
from datetime import datetime
from pydantic import BaseModel, Field

from .base import Tool


class TaskItem:
    """A single task item, matching Claude Code's task structure."""
    def __init__(self, subject: str, description: str, id: str = None):
        self.id = id or f"task_{len(_task_store) + 1}"
        self.subject = subject
        self.description = description
        self.status = "pending"  # pending, in_progress, completed, deleted
        self.blocks: list[str] = []
        self.blocked_by: list[str] = []
        self.owner: Optional[str] = None
        self.active_form: Optional[str] = None
        self.metadata: dict = {}
        self.created_at = datetime.now().isoformat()
        self.updated_at = self.created_at


# Global task store (would be scoped per-session in production)
_task_store: dict[str, TaskItem] = {}


# -- TaskCreate --

class TaskCreateInput(BaseModel):
    """Input schema for TaskCreate tool."""
    subject: str = Field(description="A brief title for the task")
    description: str = Field(description="What needs to be done")
    active_form: Optional[str] = Field(default=None, description="Present continuous form shown in spinner when in_progress")
    metadata: Optional[dict] = Field(default=None, description="Arbitrary metadata to attach to the task")


class TaskCreateTool(Tool):
    """Create a new task in the task list."""

    name = "TaskCreate"
    aliases = []
    search_hint = "create a new task for tracking progress"

    def input_schema(self) -> Type[BaseModel]:
        return TaskCreateInput

    async def call(self, args: dict, context: dict) -> dict:
        task = TaskItem(
            subject=args["subject"],
            description=args["description"],
        )
        if args.get("active_form"):
            task.active_form = args["active_form"]
        if args.get("metadata"):
            task.metadata = args["metadata"]

        _task_store[task.id] = task

        return {
            "data": {
                "id": task.id,
                "subject": task.subject,
                "status": task.status,
            },
        }

    async def description(self, input_schema: dict, options: dict) -> str:
        return "Create a new task in the task list. Use for tracking progress on complex multi-step tasks."

    def is_read_only(self, input_data: dict = None) -> bool:
        return False


# -- TaskUpdate --

class TaskUpdateInput(BaseModel):
    """Input schema for TaskUpdate tool."""
    task_id: str = Field(description="The ID of the task to update")
    status: Optional[str] = Field(default=None, description="New status: pending, in_progress, completed, or deleted")
    subject: Optional[str] = Field(default=None, description="New subject for the task")
    description: Optional[str] = Field(default=None, description="New description for the task")
    add_blocks: Optional[list[str]] = Field(default=None, description="Task IDs that this task blocks")
    add_blocked_by: Optional[list[str]] = Field(default=None, description="Task IDs that block this task")


class TaskUpdateTool(Tool):
    """Update a task's status or properties."""

    name = "TaskUpdate"
    aliases = []
    search_hint = "update task status or add dependencies"

    def input_schema(self) -> Type[BaseModel]:
        return TaskUpdateInput

    async def call(self, args: dict, context: dict) -> dict:
        task_id = args["task_id"]
        task = _task_store.get(task_id)
        if not task:
            return {"data": f"Error: Task not found: {task_id}"}

        if args.get("status"):
            task.status = args["status"]
        if args.get("subject"):
            task.subject = args["subject"]
        if args.get("description"):
            task.description = args["description"]
        if args.get("add_blocks"):
            task.blocks.extend(args["add_blocks"])
        if args.get("add_blocked_by"):
            task.blocked_by.extend(args["add_blocked_by"])

        task.updated_at = datetime.now().isoformat()

        return {
            "data": {
                "id": task.id,
                "subject": task.subject,
                "status": task.status,
            },
        }

    async def description(self, input_schema: dict, options: dict) -> str:
        return "Update a task's status (pending, in_progress, completed, deleted) or properties. Use to track progress and set up dependencies."

    def is_read_only(self, input_data: dict = None) -> bool:
        return False


# -- TaskList --

class TaskListInput(BaseModel):
    """Input schema for TaskList tool (no parameters)."""
    pass


class TaskListTool(Tool):
    """List all tasks in the task list."""

    name = "TaskList"
    aliases = []
    search_hint = "list all tasks and their statuses"

    def input_schema(self) -> Type[BaseModel]:
        return TaskListInput

    async def call(self, args: dict, context: dict) -> dict:
        tasks = [
            {
                "id": t.id,
                "subject": t.subject,
                "status": t.status,
                "owner": t.owner,
                "blocked_by": t.blocked_by,
            }
            for t in _task_store.values()
            if t.status != "deleted"
        ]

        return {
            "data": {
                "count": len(tasks),
                "tasks": tasks,
            },
        }

    async def description(self, input_schema: dict, options: dict) -> str:
        return "List all tasks and their statuses. Use to check overall progress and find available work."

    def is_read_only(self, input_data: dict = None) -> bool:
        return True


# -- TaskGet --

class TaskGetInput(BaseModel):
    """Input schema for TaskGet tool."""
    task_id: str = Field(description="The ID of the task to retrieve")


class TaskGetTool(Tool):
    """Get detailed information about a task."""

    name = "TaskGet"
    aliases = []
    search_hint = "retrieve full task details by ID"

    def input_schema(self) -> Type[BaseModel]:
        return TaskGetInput

    async def call(self, args: dict, context: dict) -> dict:
        task = _task_store.get(args["task_id"])
        if not task:
            return {"data": f"Error: Task not found: {args['task_id']}"}

        return {
            "data": {
                "id": task.id,
                "subject": task.subject,
                "description": task.description,
                "status": task.status,
                "blocks": task.blocks,
                "blocked_by": task.blocked_by,
                "owner": task.owner,
                "active_form": task.active_form,
                "metadata": task.metadata,
                "created_at": task.created_at,
                "updated_at": task.updated_at,
            },
        }

    async def description(self, input_schema: dict, options: dict) -> str:
        return "Retrieve full details of a task by its ID, including description and dependencies."

    def is_read_only(self, input_data: dict = None) -> bool:
        return True


# -- TaskStop --

class TaskStopInput(BaseModel):
    """Input schema for TaskStop tool."""
    task_id: str = Field(description="The ID of the background task to stop")


class TaskStopTool(Tool):
    """Stop a running background task."""

    name = "TaskStop"
    aliases = []
    search_hint = "stop a running background task"

    def input_schema(self) -> Type[BaseModel]:
        return TaskStopInput

    async def call(self, args: dict, context: dict) -> dict:
        task_id = args["task_id"]
        task = _task_store.get(task_id)
        if not task:
            return {"data": f"Error: Task not found: {task_id}"}

        task.status = "completed"
        task.updated_at = datetime.now().isoformat()

        return {
            "data": {
                "id": task.id,
                "status": "stopped",
            },
        }

    async def description(self, input_schema: dict, options: dict) -> str:
        return "Stop a running background task by its ID. Use for cancelling long-running operations."

    def is_read_only(self, input_data: dict = None) -> bool:
        return False


# -- TaskOutput --

class TaskOutputInput(BaseModel):
    """Input schema for TaskOutput tool."""
    task_id: str = Field(description="The task ID to get output from")
    block: bool = Field(default=True, description="Whether to wait for completion")
    timeout: int = Field(default=30000, description="Max wait time in ms")


class TaskOutputTool(Tool):
    """Retrieve output from a running or completed task."""

    name = "TaskOutput"
    aliases = []
    search_hint = "read output from a background task"

    def input_schema(self) -> Type[BaseModel]:
        return TaskOutputInput

    async def call(self, args: dict, context: dict) -> dict:
        task_id = args["task_id"]
        task = _task_store.get(task_id)
        if not task:
            return {"data": f"Error: Task not found: {task_id}"}

        return {
            "data": {
                "id": task.id,
                "subject": task.subject,
                "status": task.status,
                "result": task.metadata.get("output", ""),
            },
        }

    async def description(self, input_schema: dict, options: dict) -> str:
        return "Retrieve output from a running or completed background task."

    def is_read_only(self, input_data: dict = None) -> bool:
        return True
