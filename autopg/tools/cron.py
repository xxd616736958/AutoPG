"""Cron tools."""
import json
from pydantic import Field
from langchain_core.tools import tool

_jobs={}; _counter=0

@tool
async def cron_create(
    cron: str = Field(description="Standard 5-field cron expression: 'M H DoM Mon DoW'"),
    prompt: str = Field(description="The prompt to enqueue at each fire time"),
    recurring: bool = Field(default=True, description="True = fire on every cron match, False = fire once then auto-delete"),
) -> str:
    """Schedule a prompt to be enqueued at a future time using cron syntax."""
    global _counter; _counter+=1; jid=f"cron_{_counter}"
    _jobs[jid]={"id":jid,"cron":cron,"prompt":prompt,"recurring":recurring}
    return json.dumps({"id":jid,"cron":cron,"recurring":recurring})

@tool
async def cron_delete(
    id: str = Field(description="Job ID returned by CronCreate"),
) -> str:
    """Cancel a scheduled cron job."""
    if id in _jobs: del _jobs[id]; return json.dumps({"id":id,"status":"deleted"})
    return json.dumps(f"Error: Job not found: {id}")

@tool
async def cron_list() -> str:
    """List all scheduled cron jobs in this session."""
    return json.dumps({"count":len(_jobs),"jobs":list(_jobs.values())})
