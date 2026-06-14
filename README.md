# db-claude

An intelligent coding agent built with **LangChain** and **LangGraph**, architecturally identical to **Claude Code** and reimplemented in Python.

## Architecture

db-claude replicates the complete Claude Code architecture:

### Core Components (mirrors Claude Code src/)

| Component | Claude Code | db-claude |
|-----------|-------------|-----------|
| **Query Engine** | `src/QueryEngine.ts` | `agent/query_loop.py` → `QueryEngine` |
| **Query Loop** | `src/query.ts` | `agent/query_loop.py` → LangGraph StateGraph |
| **System Prompt** | `src/constants/prompts.ts` | `agent/system_prompt.py` |
| **Tool System** | `src/Tool.ts` | `tools/base.py` → `Tool`, `ToolRegistry` |
| **State** | Query loop state | `agent/state.py` → `AgentState` |
| **CLI/REPL** | `src/screens/REPL.tsx` | `cli/repl.py` → `ReplInterface` |
| **Commands** | `src/commands.ts` | `cli/commands.py` → `SlashCommandHandler` |
| **Memory** | `src/memdir/` | `context/memory.py` → `MemoryManager` |
| **Compaction** | `src/services/compact/` | `context/compact.py` → `CompactManager` |
| **Permissions** | `src/utils/permissions/` | `utils/permissions.py` |

### LangGraph Architecture

The agent uses a `StateGraph` with the following topology:

```
START → agent (call_model) → [tools needed?]
                ↑                    ↓ yes
                └── execute_tools ←──┘
                        ↓ no
                       END
```

Each turn:
1. **call_model** — Streams the model response with tool bindings
2. **route** — Checks if tool calls were generated
3. **execute_tools** — Runs all requested tools, returns results
4. Loop back to **call_model** with results attached

### Tools (25 tools matching Claude Code)

| Category | Tools |
|----------|-------|
| **File Operations** | Read, Write, Edit, Glob, Grep |
| **Shell** | Bash |
| **Task Management** | TaskCreate, TaskUpdate, TaskList, TaskGet, TaskStop, TaskOutput, TodoWrite |
| **Web** | WebSearch, WebFetch |
| **User Interaction** | AskUserQuestion |
| **Plan Mode** | EnterPlanMode, ExitPlanMode |
| **Worktree** | EnterWorktree, ExitWorktree |
| **Notebook** | NotebookEdit |
| **Scheduling** | CronCreate, CronDelete, CronList |
| **Orchestration** | Agent, Skill, Workflow |
| **Monitoring** | Monitor |

### System Prompt Structure

The system prompt is dynamically built from sections, identical to Claude Code:
1. Simple intro + cyber risk instruction
2. System reminders
3. Environment info (platform, shell, cwd, date)
4. Tool usage harness rules
5. Context management
6. Agent tool documentation
7. Full system section
8. Tool list with schemas
9. Memory section (when configured)

### Data Flow

```
User Input → processSlashCommands? → QueryEngine.submitMessage()
  → buildSystemPrompt()
  → LangGraph Agent Loop:
      → call_model (streaming)
      → route (tools needed?)
      → execute_tools (run Bash, Read, Write, etc.)
      → attach results
      → loop until stop_reason != 'tool_use'
  → yield result { type, subtype, result, usage, ... }
```

## Installation

```bash
pip install -e .
# Or
pip install -r requirements.txt
```

## Configuration

Set your API key:
```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

Configuration is stored in `~/.db-claude/config.json`:
```json
{
  "model": "claude-sonnet-4-6",
  "fallback_model": "claude-haiku-4-5-20251001",
  "permission_mode": "default",
  "theme": "dark"
}
```

## Usage

### Interactive Mode

```bash
db-claude
```

### Non-interactive / Print Mode

```bash
db-claude --print "Explain the architecture of this project"
echo "What does this code do?" | db-claude --print
```

### Slash Commands

Inside the REPL:
- `/help` — Show all commands
- `/model [name]` — Show or change the model
- `/clear` — Clear conversation history
- `/compact` — Manually trigger context compaction
- `/config` — Show or change configuration
- `/memory` — List stored memories
- `/cost` — Show token usage
- `/permissions [mode]` — Show or change permission mode
- `/exit` — Exit

### CLI Options

```
--model, -m          Model to use
--fallback-model     Fallback model on overload
--max-turns          Max agent turns per query
--max-budget-usd     Max USD budget
--permission-mode    default|accept_edits|bypass|plan
--print, -p          Print mode (non-interactive)
--verbose            Verbose output
--version, -v        Show version
--system-prompt      Custom system prompt
--init               Initialize CLAUDE.md
```

## Project Structure

```
db_claude/
├── __init__.py
├── main.py              # CLI entry point
├── agent/
│   ├── __init__.py
│   ├── query_loop.py    # QueryEngine + LangGraph loop
│   ├── state.py         # AgentState, ToolUseContext
│   └── system_prompt.py # System prompt builder
├── tools/
│   ├── __init__.py      # ToolRegistry, create_default_tools()
│   ├── base.py          # Tool, PermissionResult
│   ├── bash.py          # Bash tool
│   ├── file_read.py     # FileRead tool
│   ├── file_write.py    # FileWrite tool
│   ├── file_edit.py     # FileEdit tool
│   ├── glob.py          # Glob tool
│   ├── grep.py          # Grep tool
│   ├── task.py          # 6 task management tools
│   ├── web_search.py    # WebSearch + WebFetch
│   ├── todo_write.py    # TodoWrite tool
│   ├── notebook_edit.py # NotebookEdit tool
│   ├── ask_user.py      # AskUserQuestion tool
│   ├── plan_mode.py     # Plan mode + Worktree tools
│   ├── cron.py          # 3 cron scheduling tools
│   ├── agent_tool.py    # Agent (subagent) tool
│   ├── skill.py         # Skill tool
│   ├── workflow.py      # Workflow tool
│   └── monitor.py       # Monitor tool
├── context/
│   ├── __init__.py
│   ├── memory.py        # Persistent memory system
│   └── compact.py       # Context compaction
├── cli/
│   ├── __init__.py
│   ├── repl.py          # Interactive REPL (prompt_toolkit)
│   └── commands.py      # Slash commands
└── utils/
    ├── __init__.py
    ├── config.py         # Configuration management
    ├── messages.py       # Message helpers
    └── permissions.py    # Permission system
```

## License

MIT
