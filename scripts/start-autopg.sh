#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${AUTOPG_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
cd "$PROJECT_DIR"

: "${AUTOPG_DATABASE_URI:=postgresql://${USER:-postgres}@localhost:5432/db_agent}"
: "${AUTOPG_POSTGRES_ACCESS_MODE:=restricted}"
: "${AUTOPG_START_POSTGRES:=auto}"
: "${AUTOPG_MODE:=interactive}"
: "${AUTOPG_API_PORT:=8010}"

export AUTOPG_DATABASE_URI
export AUTOPG_POSTGRES_ACCESS_MODE

log() { printf '\033[1;34m[AutoPG]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[AutoPG]\033[0m %s\n' "$*"; }

log "Project: $PROJECT_DIR"
log "Database URI: ${AUTOPG_DATABASE_URI}"
log "PostgreSQL MCP access mode: ${AUTOPG_POSTGRES_ACCESS_MODE}"

if [[ "$AUTOPG_START_POSTGRES" != "false" ]]; then
  if ! pg_isready -h localhost -p 5432 >/dev/null 2>&1; then
    if command -v brew >/dev/null 2>&1; then
      warn "PostgreSQL is not ready; trying Homebrew service start..."
      brew services start postgresql@17 >/dev/null 2>&1 || brew services start postgresql >/dev/null 2>&1 || true
      sleep 2
    fi
  fi
fi

log "Checking PostgreSQL..."
if ! pg_isready -h localhost -p 5432; then
  warn "PostgreSQL is not accepting connections on localhost:5432. Start it first or set AUTOPG_DATABASE_URI."
  exit 1
fi

log "Testing database connection..."
psql "$AUTOPG_DATABASE_URI" -c "select current_database() as database, current_user as user, version();" >/tmp/autopg-db-check.out
cat /tmp/autopg-db-check.out

log "Testing built-in postgres_mcp through AutoPG MCP manager..."
python - <<'PYSMOKE' >/tmp/autopg-mcp-check.out 2>&1
import asyncio
from autopg.mcp import MCPManager, load_mcp_configs

async def main():
    manager = MCPManager()
    tools = await manager.start(load_mcp_configs())
    names = [t.name for t in tools]
    print("tools=", names)
    tool = next((t for t in tools if t.name == "mcp__postgres__list_schemas"), None)
    if tool is None:
        raise RuntimeError("mcp__postgres__list_schemas not found")
    result = await tool.ainvoke({})
    print(str(result)[:1000])
    await manager.stop()

asyncio.run(main())
PYSMOKE
if [[ $? -ne 0 ]]; then
  cat /tmp/autopg-mcp-check.out
  warn "AutoPG + postgres_mcp smoke test failed."
  exit 1
fi
cat /tmp/autopg-mcp-check.out

case "$AUTOPG_MODE" in
  interactive)
    log "Starting AutoPG database tuning agent..."
    exec python -m autopg.main
    ;;
  api)
    log "Starting AutoPG FastAPI server on 127.0.0.1:${AUTOPG_API_PORT}..."
    exec python -m uvicorn autopg.backend.server:app --host 127.0.0.1 --port "$AUTOPG_API_PORT"
    ;;
  check)
    log "Check mode complete."
    ;;
  *)
    warn "Unknown AUTOPG_MODE=$AUTOPG_MODE. Use interactive, api, or check."
    exit 2
    ;;
esac
