#!/usr/bin/env bash
set -euo pipefail

: "${AUTOPG_API_PORT:=8010}"
: "${AUTOPG_STOP_POSTGRES:=false}"

log() { printf '\033[1;34m[AutoPG]\033[0m %s\n' "$*"; }

log "Stopping AutoPG API on port ${AUTOPG_API_PORT} if running..."
if lsof -tiTCP:"$AUTOPG_API_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  kill $(lsof -tiTCP:"$AUTOPG_API_PORT" -sTCP:LISTEN) 2>/dev/null || true
fi

log "Stopping standalone postgres_mcp SSE processes if running..."
pkill -f "postgres_mcp.*transport=sse" 2>/dev/null || true
pkill -f "postgres-mcp.*transport=sse" 2>/dev/null || true

log "Stopping leftover postgres_mcp stdio processes if running..."
pkill -f "postgres_mcp" 2>/dev/null || true
pkill -f "postgres-mcp" 2>/dev/null || true

if [[ "$AUTOPG_STOP_POSTGRES" == "true" ]]; then
  log "Stopping PostgreSQL Homebrew service..."
  brew services stop postgresql@17 2>/dev/null || brew services stop postgresql 2>/dev/null || true
else
  log "Leaving PostgreSQL running. Set AUTOPG_STOP_POSTGRES=true to stop it too."
fi

log "Done."
