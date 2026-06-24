# db-claude — PostgreSQL Tuning Agent

`db-claude` is a professional PostgreSQL database tuning agent built with
LangChain, LangGraph, and a built-in `postgres-mcp` integration.

The project packages the agent runtime and PostgreSQL MCP tool together so that
one command can start a database-aware assistant for schema exploration, health
checks, slow-query analysis, execution-plan inspection, and index tuning.

## What this agent can do

- List schemas, tables, views, sequences, and indexes.
- Inspect table structure, DDL, columns, constraints, and index definitions.
- Run safe SQL through `postgres-mcp`.
- Analyze database health:
  - invalid indexes
  - duplicate indexes
  - index bloat
  - unused indexes
  - connection utilization
  - vacuum / transaction ID risk
  - sequence exhaustion
  - replication status
  - buffer cache hit ratio
  - invalid constraints
- Find slow and resource-intensive queries through `pg_stat_statements`.
- Explain query plans.
- Recommend indexes for individual queries or workloads.

## Architecture

```text
User
  ↓
db-claude CLI / API
  ↓
LangGraph agent loop
  ↓
Built-in tools + built-in postgres-mcp
  ↓
PostgreSQL
```

`postgres-mcp` is built in by default. You do **not** need to create a local
`.claude/.mcp.json` for normal usage. The MCP loader automatically creates a
`postgres` server using these environment variables:

| Variable | Default | Description |
|---|---|---|
| `DB_CLAUDE_ENABLE_POSTGRES_MCP` | `true` | Enable built-in PostgreSQL MCP |
| `DB_CLAUDE_DATABASE_URI` | `postgresql://$USER@localhost:5432/db_agent` | PostgreSQL connection URI |
| `DB_CLAUDE_POSTGRES_ACCESS_MODE` | `restricted` | `restricted` or `unrestricted` |
| `DB_CLAUDE_POSTGRES_MCP_COMMAND` | `uvx` | Command used to launch MCP |
| `DB_CLAUDE_POSTGRES_MCP_PACKAGE` | `postgres-mcp` | Package/entrypoint passed to `uvx` |

If you do provide `~/.db-claude/config.json` `mcpServers` or project
`.claude/.mcp.json`, those configs override the built-in one.

## Requirements

- macOS/Linux
- Python 3.11+
- PostgreSQL running locally or remotely
- `psql` and `pg_isready` available on `PATH`
- `uv` / `uvx` recommended
- DeepSeek or Anthropic-compatible API key

For Homebrew PostgreSQL:

```bash
brew install postgresql@17
brew services start postgresql@17
```

For `uv`:

```bash
brew install uv
```

## Installation

```bash
git clone https://github.com/xxd616736958/db-claude.git
cd db-claude
pip install -e .
```

Or with a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

`pyproject.toml` is the source of truth for Python dependencies. `requirements.txt` is intentionally kept as a thin compatibility wrapper that runs `pip install -e .` for platforms that still expect a requirements file.

## Configure the LLM

Create or edit:

```bash
mkdir -p ~/.db-claude
nano ~/.db-claude/config.json
```

Example DeepSeek configuration:

```json
{
  "provider": "deepseek",
  "model": "deepseek-v4-flash",
  "api_key": "sk-your-key",
  "base_url": "https://api.deepseek.com/v1",
  "permission_mode": "default",
  "verbose": false,
  "theme": "dark"
}
```

You can also set the key by environment variable:

```bash
export DEEPSEEK_API_KEY=sk-your-key
```

## Configure the database

Set the database URI:

```bash
export DB_CLAUDE_DATABASE_URI="postgresql://nncc@localhost:5432/db_agent"
```

The recommended default mode is read-only/restricted:

```bash
export DB_CLAUDE_POSTGRES_ACCESS_MODE=restricted
```

Use unrestricted mode only for development databases:

```bash
export DB_CLAUDE_POSTGRES_ACCESS_MODE=unrestricted
```

## One-click startup

The project includes a one-click startup script:

```bash
./scripts/start-db-claude.sh
```

It will:

1. enter the project directory
2. check/start PostgreSQL when possible
3. verify the database connection
4. verify db-claude + built-in postgres-mcp
5. start the interactive database tuning agent

Common examples:

```bash
# Start interactive tuning agent
DB_CLAUDE_DATABASE_URI="postgresql://nncc@localhost:5432/db_agent" \
./scripts/start-db-claude.sh

# Only run checks, do not enter REPL
DB_CLAUDE_MODE=check ./scripts/start-db-claude.sh

# Start FastAPI service instead of REPL
DB_CLAUDE_MODE=api DB_CLAUDE_API_PORT=8010 ./scripts/start-db-claude.sh
```

## Daily usage

Interactive mode:

```bash
db-claude
```

Example prompts:

```text
列出所有 schema
进行数据库健康检查
查看最慢/最耗资源的查询
分析 big_orders_demo 表的索引健康
解释这条 SQL 的执行计划：select count(*) from big_orders_demo;
给我优化 public.big_orders_demo 的索引建议
```

Non-interactive mode:

```bash
python -m db_claude.main --print "列出所有 schema"
python -m db_claude.main --print "进行数据库健康检查"
python -m db_claude.main --print "查看最慢/最耗资源的查询"
```

## FastAPI mode

Start API server:

```bash
DB_CLAUDE_MODE=api DB_CLAUDE_API_PORT=8010 ./scripts/start-db-claude.sh
```

Check:

```bash
curl http://127.0.0.1:8010/api/sessions
```

## Stop services

Stop db-claude API, standalone postgres-mcp processes, and leftover MCP child
processes:

```bash
./scripts/stop-db-claude.sh
```

By default, the stop script leaves PostgreSQL running. To stop PostgreSQL too:

```bash
DB_CLAUDE_STOP_POSTGRES=true ./scripts/stop-db-claude.sh
```

For an interactive `db-claude` session, exit with:

```text
/exit
```

or press `Ctrl-D`.

## Manual health checks

Check PostgreSQL:

```bash
pg_isready -h localhost -p 5432
psql "$DB_CLAUDE_DATABASE_URI" -c "select current_database(), current_user, version();"
```

Check db-claude + built-in postgres-mcp:

```bash
python -m db_claude.main --print "列出所有 schema"
```

Check DeepSeek connectivity:

```bash
curl -I https://api.deepseek.com
```

## `pg_stat_statements` for slow-query analysis

The `查看最慢/最耗资源的查询` workflow is most useful when
`pg_stat_statements` is enabled.

Check extension:

```sql
SELECT * FROM pg_extension WHERE extname = 'pg_stat_statements';
```

Create extension in the target database:

```sql
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
```

If needed, add this to PostgreSQL config and restart:

```text
shared_preload_libraries = 'pg_stat_statements'
```

Homebrew restart:

```bash
brew services restart postgresql@17
```

## MCP configuration override

Built-in MCP is enough for most deployments. If you want to override it, copy the committed example file:

```bash
cp .claude/.mcp.example.json .claude/.mcp.json
```

Then edit `.claude/.mcp.json`:

```json
{
  "mcpServers": {
    "postgres": {
      "type": "stdio",
      "command": "uvx",
      "args": ["postgres-mcp", "--access-mode=restricted"],
      "env": {
        "DATABASE_URI": "postgresql://nncc@localhost:5432/db_agent"
      }
    }
  }
}
```

Project config overrides the built-in config.

## Development notes

Recent compatibility fixes include:

- `langchain-mcp-adapters >= 0.2`: use `await client.get_tools()` instead of the
  old async context manager API.
- MCP `StructuredTool` compatibility in the REPL: safely handle tools without
  `aliases`, `format_call`, or `format_result`.
- Conversation repair for interrupted tool calls to avoid OpenAI-compatible
  `tool_calls must be followed by tool messages` errors.

## GitHub deployment flow

```bash
git status
git add README.md pyproject.toml requirements.txt scripts/ db_claude/
git commit -m "feat: package db-claude as PostgreSQL tuning agent with built-in postgres-mcp"
git push origin feature/database-agent-20260618
```

Create a pull request into `main` from GitHub, or merge locally when ready.

## License

MIT
