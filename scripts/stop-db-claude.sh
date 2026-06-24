#!/usr/bin/env bash
set -euo pipefail

: "${DB_CLAUDE_API_PORT:=8010}"
: "${DB_CLAUDE_STOP_POSTGRES:=false}"

log() { printf '\033[1;34m[db-claude]\033[0m %s\n' "$*"; }

log "Stopping db-claude API on port ${DB_CLAUDE_API_PORT} if running..."
if lsof -tiTCP:"$DB_CLAUDE_API_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  kill $(lsof -tiTCP:"$DB_CLAUDE_API_PORT" -sTCP:LISTEN) 2>/dev/null || true
fi

log "Stopping standalone postgres-mcp SSE processes if running..."
pkill -f "postgres-mcp.*transport=sse" 2>/dev/null || true

log "Stopping leftover postgres-mcp stdio processes if running..."
pkill -f "postgres-mcp" 2>/dev/null || true

if [[ "$DB_CLAUDE_STOP_POSTGRES" == "true" ]]; then
  log "Stopping PostgreSQL Homebrew service..."
  brew services stop postgresql@17 2>/dev/null || brew services stop postgresql 2>/dev/null || true
else
  log "Leaving PostgreSQL running. Set DB_CLAUDE_STOP_POSTGRES=true to stop it too."
fi

log "Done."
