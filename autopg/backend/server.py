"""
FastAPI server — API Gateway for AutoPG.
Routes: agent proxy, sessions CRUD, audit query, static files.
"""
import os, logging
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
import httpx

logger = logging.getLogger(__name__)

LANGGRAPH_URL = os.environ.get("LANGGRAPH_URL", "http://127.0.0.1:8001")
AUTH_TOKENS = set(
    t.strip() for t in os.environ.get("AUTOPG_TOKENS", "").split(",") if t.strip()
)
STATIC_DIR = os.environ.get("AUTOPG_STATIC_DIR", "")


def create_app() -> FastAPI:
    app = FastAPI(title="AutoPG API", version="1.0.0")

    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
    )

    async def _check_auth(request: Request):
        if not AUTH_TOKENS:
            return  # No auth configured — allow all
        token = request.headers.get("X-API-Key", "")
        if token not in AUTH_TOKENS:
            raise HTTPException(401, "Invalid API key")

    # ── Agent proxy ──
    @app.api_route("/api/agent/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
    async def agent_proxy(path: str, request: Request):
        await _check_auth(request)
        body = await request.body()
        async with httpx.AsyncClient(timeout=300) as client:
            resp = await client.request(
                method=request.method,
                url=f"{LANGGRAPH_URL}/{path}",
                headers={k: v for k, v in request.headers.items()
                         if k.lower() not in ("host", "content-length")},
                content=body,
            )
        if "stream" in path.lower():
            return StreamingResponse(
                resp.aiter_bytes(),
                media_type=resp.headers.get("content-type", "text/event-stream"),
                headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
            )
        return JSONResponse(resp.json(), status_code=resp.status_code)

    # ── Sessions CRUD ──
    @app.get("/api/sessions")
    async def list_sessions():
        from ..utils.session import list_sessions as _list
        return _list(limit=50)

    @app.get("/api/sessions/{session_id}")
    async def get_session(session_id: str):
        from ..utils.session import load_session
        s = load_session(session_id)
        if not s:
            raise HTTPException(404, "Session not found")
        return s

    @app.delete("/api/sessions/{session_id}")
    async def delete_session(session_id: str):
        from ..utils.session import delete_session as _del
        _del(session_id)
        return {"status": "deleted"}

    # ── Audit ──
    @app.get("/api/audit")
    async def query_audit(session_id: str = None, limit: int = 100):
        from ..utils.session import load_session
        if session_id:
            s = load_session(session_id)
            return s.get("messages", [])[:limit] if s else []
        return []

    # ── Static (Web frontend) ──
    if STATIC_DIR and os.path.isdir(STATIC_DIR):
        @app.get("/{full_path:path}")
        async def serve_static(full_path: str):
            fp = os.path.join(STATIC_DIR, full_path or "index.html")
            if os.path.isfile(fp):
                return FileResponse(fp)
            return FileResponse(os.path.join(STATIC_DIR, "index.html"))

    return app


app = create_app()
