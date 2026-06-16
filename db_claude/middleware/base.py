"""
AgentMiddleware base class + MiddlewareStack.
Aligns with LangChain's AgentMiddleware API on raw LangGraph StateGraph.
"""
from typing import Any, Optional


class AgentMiddleware:
    """Base middleware. Each hook returns None (no change) or dict (merge into state).
    Aligns with langchain.agents.middleware.AgentMiddleware signature."""

    # ── before/after hooks (return dict to modify state) ──
    async def abefore_agent(self, state: dict, runtime: dict) -> Optional[dict]:
        return None

    async def abefore_model(self, state: dict, runtime: dict) -> Optional[dict]:
        return None

    async def aafter_model(self, state: dict, runtime: dict) -> Optional[dict]:
        return None

    async def aafter_agent(self, state: dict, runtime: dict) -> Optional[dict]:
        return None

    # ── wrap hooks (can short-circuit, modify request/response) ──
    async def awrap_model_call(self, request: dict, handler) -> Any:
        return await handler(request)

    async def awrap_tool_call(self, request: dict, handler) -> Any:
        return await handler(request)


class MiddlewareStack:
    """Composes multiple AgentMiddleware instances. Runs before hooks in order,
    wrap hooks as onion (outer→inner), after hooks in reverse order."""

    def __init__(self, middlewares: list[AgentMiddleware]):
        self._mws = middlewares

    # ── Run all before_X hooks in order, accumulating state changes ──
    async def run_before_agent(self, state: dict, runtime: dict) -> dict:
        for mw in self._mws:
            delta = await mw.abefore_agent(state, runtime)
            if delta:
                state = {**state, **delta}
        return state

    async def run_before_model(self, state: dict, runtime: dict) -> dict:
        for mw in self._mws:
            delta = await mw.abefore_model(state, runtime)
            if delta:
                state = {**state, **delta}
        return state

    async def run_after_model(self, state: dict, runtime: dict) -> dict:
        for mw in reversed(self._mws):
            delta = await mw.aafter_model(state, runtime)
            if delta:
                state = {**state, **delta}
        return state

    async def run_after_agent(self, state: dict, runtime: dict) -> dict:
        for mw in reversed(self._mws):
            delta = await mw.aafter_agent(state, runtime)
            if delta:
                state = {**state, **delta}
        return state

    # ── Wrap hooks: onion nesting (outermost middleware first) ──
    async def run_wrap_model_call(self, request: dict, handler) -> Any:
        wrapped = handler
        for mw in reversed(self._mws):
            inner = wrapped
            wrapped = lambda r, mw=mw: mw.awrap_model_call(r, inner)
        return await wrapped(request)

    async def run_wrap_tool_call(self, request: dict, handler) -> Any:
        wrapped = handler
        for mw in reversed(self._mws):
            inner = wrapped
            wrapped = lambda r, mw=mw: mw.awrap_tool_call(r, inner)
        return await wrapped(request)
