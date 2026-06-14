"""
Cron tools for db-claude.
Architecturally identical to Claude Code's CronCreateTool, CronDeleteTool, CronListTool.
"""
from typing import Type, Optional
from pydantic import BaseModel, Field

from .base import Tool

# Global cron store (scoped per-session in production)
_cron_jobs: dict[str, dict] = {}
_cron_counter = 0


class CronCreateInput(BaseModel):
    """Input schema for CronCreate tool."""
    cron: str = Field(description="Standard 5-field cron expression in local time: 'M H DoM Mon DoW'")
    prompt: str = Field(description="The prompt to enqueue at each fire time")
    recurring: bool = Field(default=True, description="true = fire on every cron match. false = fire once then auto-delete")
    durable: bool = Field(default=False, description="true = persist to disk and survive restarts")


class CronCreateTool(Tool):
    """Schedule a prompt to be enqueued at a future time."""

    name = "CronCreate"
    aliases = []
    search_hint = "schedule a recurring prompt"

    def input_schema(self) -> Type[BaseModel]:
        return CronCreateInput

    async def call(self, args: dict, context: dict) -> dict:
        global _cron_counter, _cron_jobs
        _cron_counter += 1
        job_id = f"cron_{_cron_counter}"

        _cron_jobs[job_id] = {
            "id": job_id,
            "cron": args["cron"],
            "prompt": args["prompt"],
            "recurring": args.get("recurring", True),
            "durable": args.get("durable", False),
        }

        return {
            "data": {
                "id": job_id,
                "cron": args["cron"],
                "recurring": args.get("recurring", True),
            },
        }

    async def description(self, input_schema: dict, options: dict) -> str:
        return "Schedule a prompt to run at a future time using cron syntax. Use for recurring tasks, reminders, or delayed execution."

    def is_read_only(self, input_data: dict = None) -> bool:
        return False


class CronDeleteInput(BaseModel):
    """Input schema for CronDelete tool."""
    id: str = Field(description="Job ID returned by CronCreate")


class CronDeleteTool(Tool):
    """Cancel a scheduled cron job."""

    name = "CronDelete"
    aliases = []
    search_hint = "cancel a scheduled cron job"

    def input_schema(self) -> Type[BaseModel]:
        return CronDeleteInput

    async def call(self, args: dict, context: dict) -> dict:
        job_id = args["id"]
        if job_id in _cron_jobs:
            del _cron_jobs[job_id]
            return {"data": {"id": job_id, "status": "deleted"}}
        return {"data": f"Error: Job not found: {job_id}"}

    async def description(self, input_schema: dict, options: dict) -> str:
        return "Cancel a cron job previously scheduled with CronCreate."

    def is_read_only(self, input_data: dict = None) -> bool:
        return False


class CronListInput(BaseModel):
    """Input schema for CronList tool (no parameters)."""
    pass


class CronListTool(Tool):
    """List all scheduled cron jobs."""

    name = "CronList"
    aliases = []
    search_hint = "list scheduled cron jobs"

    def input_schema(self) -> Type[BaseModel]:
        return CronListInput

    async def call(self, args: dict, context: dict) -> dict:
        return {
            "data": {
                "count": len(_cron_jobs),
                "jobs": list(_cron_jobs.values()),
            },
        }

    async def description(self, input_schema: dict, options: dict) -> str:
        return "List all cron jobs scheduled via CronCreate in this session."

    def is_read_only(self, input_data: dict = None) -> bool:
        return True
