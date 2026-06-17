"""Cron tools."""
import json
from pydantic import BaseModel, Field
from langchain_core.tools import tool

_jobs={}; _counter=0

class CronCreateInput(BaseModel):
    cron: str = Field(description="5-field cron expression: M H DoM Mon DoW")
    prompt: str = Field(description="Prompt to enqueue at each fire time")
    recurring: bool = Field(default=True)
@tool(args_schema=CronCreateInput)
async def cron_create(cron: str, prompt: str, recurring: bool = True) -> str:
    """Schedule a prompt to run at a future time using cron syntax."""
    global _counter; _counter+=1; jid=f"cron_{_counter}"
    _jobs[jid]={"id":jid,"cron":cron,"prompt":prompt,"recurring":recurring}
    return json.dumps({"id":jid,"cron":cron,"recurring":recurring})

class CronDeleteInput(BaseModel):
    id: str = Field(description="Job ID from CronCreate")
@tool(args_schema=CronDeleteInput)
async def cron_delete(id: str) -> str:
    """Cancel a scheduled cron job."""
    if id in _jobs: del _jobs[id]; return json.dumps({"id":id,"status":"deleted"})
    return json.dumps(f"Error: Job not found: {id}")

class CronListInput(BaseModel): pass
@tool(args_schema=CronListInput)
async def cron_list() -> str:
    """List all scheduled cron jobs."""
    return json.dumps({"count":len(_jobs),"jobs":list(_jobs.values())})
