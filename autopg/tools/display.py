"""
ToolDisplay — AutoPG output formatting registry.
Separate from tool execution. CLI/REPL uses this; Web frontend would use its own components.
"""
import os, json
from typing import Any, Callable


# Registry: tool_name → {call, result, is_destructive, is_read_only, activity}
_tool_display: dict[str, dict] = {}


def register(name: str, *, call: Callable = None, result: Callable = None,
             is_destructive: Callable = None, is_read_only: Callable = None,
             activity: Callable = None):
    """Register display metadata for a tool."""
    if name not in _tool_display:
        _tool_display[name] = {}
    if call: _tool_display[name]["call"] = call
    if result: _tool_display[name]["result"] = result
    if is_destructive: _tool_display[name]["is_destructive"] = is_destructive
    if is_read_only: _tool_display[name]["is_read_only"] = is_read_only
    if activity: _tool_display[name]["activity"] = activity


def format_call(name: str, args: dict) -> str:
    d = _tool_display.get(name, {})
    fn = d.get("call")
    return fn(args) if fn else name


def format_result(name: str, data: Any) -> str:
    d = _tool_display.get(name, {})
    fn = d.get("result")
    if fn:
        try:
            if isinstance(data, str) and data.startswith("{"):
                return fn(json.loads(data))
            return fn(data)
        except Exception:
            pass
    s = str(data); return s[:120] + ("..." if len(s) > 120 else "")


def is_destructive(name: str, args: dict) -> bool:
    fn = _tool_display.get(name, {}).get("is_destructive")
    return fn(args) if fn else False


def is_read_only(name: str, args: dict) -> bool:
    fn = _tool_display.get(name, {}).get("is_read_only")
    return fn(args) if fn else False


def activity(name: str, args: dict) -> str:
    fn = _tool_display.get(name, {}).get("activity")
    return fn(args) if fn else name


# ═══════════════════════════════════════════════════
# Register all 28 tools
# ═══════════════════════════════════════════════════

register("bash",
    call=lambda a: f"Bash({a.get('command','')[:80]})",
    result=lambda d: (
        (lambda lines: lines[0][:120] if len(lines) <= 3 else f"{len(lines)} lines of output")
        (d.get("stdout","").strip().split("\n") if d.get("stdout","").strip() else [])
    ) or (d.get("stderr","").strip().split("\n")[0][:120] if d.get("stderr","") else f"exit={d.get('exit_code','?')}"),
    is_destructive=lambda a: any(p in a.get('command','') for p in ("rm ","rmdir ",">","chmod","chown","kill ")),
    is_read_only=lambda a: a.get('command','').startswith(("ls ","cat ","head ","tail ","grep ","find ","wc ","echo ","which ","git ","pwd","env")),
    activity=lambda a: a.get('description') or f"Running `{a.get('command','')[:60]}`",
)

register("read",
    call=lambda a: f"Read({os.path.basename(a.get('file_path','?'))})",
    result=lambda d: (lambda s: f"{len([l for l in s.strip().split(chr(10)) if l.strip() and not l.startswith('...')])} lines")(d) if isinstance(d, str) and "\n" in d else str(d)[:120],
    is_read_only=lambda a: True,
    activity=lambda a: f"Reading {os.path.basename(a.get('file_path',''))}",
)

register("write",
    call=lambda a: f"Write({os.path.basename(a.get('file_path','?'))})",
    result=lambda d: f"{'overwritten' if d.get('existed_before') else 'written'} ({d.get('size',0):,} bytes)" if d.get('size') else d.get('status','done'),
    is_destructive=lambda a: True,
    activity=lambda a: f"Writing {os.path.basename(a.get('file_path',''))}",
)

register("edit",
    call=lambda a: f"Edit({os.path.basename(a.get('file_path','?'))})",
    result=lambda d: f"replaced {d.get('occurrences_replaced',0)}/{d.get('total_occurrences',0)} occurrences",
    is_destructive=lambda a: True,
    activity=lambda a: f"Editing {os.path.basename(a.get('file_path',''))}",
)

register("glob",
    call=lambda a: f"Glob({a.get('pattern','*')})",
    result=lambda d: f"{d.get('count',0)} files" + (f": {', '.join(r[:40] for r in d.get('results',[])[:3])}" + (f" ... +{d.get('count',0)-3} more" if d.get('count',0)>3 else "") if d.get('results') else ""),
    is_read_only=lambda a: True,
    activity=lambda a: f"Globbing {a.get('pattern','')}",
)

register("grep",
    call=lambda a: f"Grep({a.get('pattern','')[:60]})",
    result=lambda d: f"{d.get('count',0)} matches" + (f": {'; '.join(r[:60] for r in d.get('results',[])[:3])}" if d.get('results') else ""),
    is_read_only=lambda a: True,
    activity=lambda a: f"Searching for '{a.get('pattern','')}'",
)

register("web_search",
    call=lambda a: f"WebSearch({a.get('query','')[:60]})",
    result=lambda d: f"{d.get('count',0)} results",
    is_read_only=lambda a: True,
    activity=lambda a: f"Searching for '{a.get('query','')}'",
)

register("web_fetch",
    call=lambda a: f"WebFetch({a.get('url','')[:60]})",
    result=lambda d: d.get('content','')[:120] if isinstance(d, dict) else str(d)[:120],
    is_read_only=lambda a: True,
    activity=lambda a: f"Fetching {a.get('url','')[:60]}",
)

register("todo_write",
    call=lambda a: "TodoWrite",
    result=lambda d: f"{d.get('counts',{}).get('total',0)} items",
    is_read_only=lambda a: False,
    activity=lambda a: "Writing todos",
)

register("notebook_edit",
    call=lambda a: f"NotebookEdit({os.path.basename(a.get('notebook_path','?'))})",
    result=lambda d: d.get('status','done'),
    is_read_only=lambda a: False,
    activity=lambda a: f"Editing {os.path.basename(a.get('notebook_path',''))}",
)

register("ask_user_question",
    call=lambda a: "AskUserQuestion",
    result=lambda d: d.get('status','presented'),
    is_read_only=lambda a: True,
    activity=lambda a: "Asking user",
)

register("task_create",
    call=lambda a: f"TaskCreate({a.get('subject','')})",
    result=lambda d: f"task {d.get('id','?')}: {d.get('subject','')}",
    is_read_only=lambda a: False,
    activity=lambda a: f"Creating task: {a.get('subject','')}",
)

register("task_update",
    call=lambda a: f"TaskUpdate({a.get('task_id','')})",
    result=lambda d: f"status={d.get('status','?')}",
    is_read_only=lambda a: False,
    activity=lambda a: f"Updating task {a.get('task_id','')}",
)

register("task_list",
    call=lambda a: "TaskList",
    result=lambda d: f"{d.get('count',0)} tasks",
    is_read_only=lambda a: True,
    activity=lambda a: "Listing tasks",
)

register("task_get",
    call=lambda a: f"TaskGet({a.get('task_id','')})",
    result=lambda d: f"task {d.get('id','?')}",
    is_read_only=lambda a: True,
    activity=lambda a: f"Getting task {a.get('task_id','')}",
)

register("task_stop",
    call=lambda a: f"TaskStop({a.get('task_id','')})",
    result=lambda d: d.get('status','stopped'),
    is_read_only=lambda a: False,
    activity=lambda a: f"Stopping task {a.get('task_id','')}",
)

register("task_output",
    call=lambda a: f"TaskOutput({a.get('task_id','')})",
    result=lambda d: d.get('result','')[:120],
    is_read_only=lambda a: True,
    activity=lambda a: f"Reading output of task {a.get('task_id','')}",
)

register("enter_plan_mode",
    call=lambda a: "EnterPlanMode",
    result=lambda d: d.get('status','entered'),
    is_read_only=lambda a: False,
    activity=lambda a: "Entering plan mode",
)

register("exit_plan_mode",
    call=lambda a: "ExitPlanMode",
    result=lambda d: d.get('status','exited'),
    is_read_only=lambda a: False,
    activity=lambda a: "Exiting plan mode",
)

register("enter_worktree",
    call=lambda a: f"EnterWorktree({a.get('name','?')})",
    result=lambda d: d.get('status','entered'),
    is_read_only=lambda a: False,
    activity=lambda a: "Entering worktree",
)

register("exit_worktree",
    call=lambda a: f"ExitWorktree({a.get('action','keep')})",
    result=lambda d: d.get('status','exited'),
    is_read_only=lambda a: False,
    activity=lambda a: "Exiting worktree",
)

register("cron_create",
    call=lambda a: f"CronCreate({a.get('cron','')})",
    result=lambda d: f"job {d.get('id','?')}",
    is_read_only=lambda a: False,
    activity=lambda a: "Creating cron job",
)

register("cron_delete",
    call=lambda a: f"CronDelete({a.get('id','')})",
    result=lambda d: d.get('status','deleted'),
    is_read_only=lambda a: False,
    activity=lambda a: "Deleting cron job",
)

register("cron_list",
    call=lambda a: "CronList",
    result=lambda d: f"{d.get('count',0)} jobs",
    is_read_only=lambda a: True,
    activity=lambda a: "Listing cron jobs",
)

register("agent",
    call=lambda a: f"Agent({a.get('description','')[:40]}{':'+a.get('subagent_type','') if a.get('subagent_type') else ''})",
    result=lambda d: d.get('status','') or (d.get('result','')[:120] if isinstance(d, dict) else str(d)[:120]),
    is_read_only=lambda a: False,
    activity=lambda a: f"Agent: {a.get('description','')}",
)

register("skill",
    call=lambda a: f"Skill({a.get('skill','')})",
    result=lambda d: d.get('status','invoked'),
    is_read_only=lambda a: False,
    activity=lambda a: f"Skill: {a.get('skill','')}",
)

register("workflow",
    call=lambda a: f"Workflow({a.get('name','custom')})",
    result=lambda d: d.get('status','executed'),
    is_read_only=lambda a: False,
    activity=lambda a: f"Workflow: {a.get('name','custom')}",
)

register("monitor",
    call=lambda a: f"Monitor({a.get('description','')})",
    result=lambda d: d.get('status','started'),
    is_read_only=lambda a: False,
    activity=lambda a: f"Monitor: {a.get('description','')}",
)
