"""
AgentMiddleware base class + MiddlewareStack.
Aligns with LangChain AgentMiddleware API on raw StateGraph.
Hooks receive context: AgentContext (not raw dict).
"""
from typing import Optional, Any


class AgentMiddleware:
    """Base middleware. Each hook can return None (no change) or dict (merge into state)."""

    async def abefore_agent(self, state: dict, context) -> Optional[dict]:
        return None

    async def abefore_model(self, state: dict, context) -> Optional[dict]:
        return None

    async def aafter_model(self, state: dict, context) -> Optional[dict]:
        return None

    async def aafter_agent(self, state: dict, context) -> Optional[dict]:
        return None

    async def awrap_model_call(self, state: dict, context, handler) -> Any:
        return await handler(state)

    async def awrap_tool_call(self, state: dict, context, handler) -> Any:
        return await handler(state)


class MiddlewareStack:
    """Composes AgentMiddleware instances. before = order, after = reverse, wrap = onion."""

    def __init__(self, middlewares: list[AgentMiddleware]):
        self._mws = middlewares

    async def run_abefore_model(self, state: dict, context) -> dict:
        for mw in self._mws:
            delta = await mw.abefore_model(state, context)
            if delta: state = {**state, **delta}
        return state

    async def run_aafter_model(self, state: dict, context) -> dict:
        for mw in reversed(self._mws):
            delta = await mw.aafter_model(state, context)
            if delta: state = {**state, **delta}
        return state

    async def run_abefore_agent(self, state: dict, context) -> dict:
        for mw in self._mws:
            delta = await mw.abefore_agent(state, context)
            if delta: state = {**state, **delta}
        return state

    async def run_aafter_agent(self, state: dict, context) -> dict:
        for mw in reversed(self._mws):
            delta = await mw.aafter_agent(state, context)
            if delta: state = {**state, **delta}
        return state

    async def run_awrap_tool_call(self, state: dict, context, handler) -> Any:
        wrapped = handler
        for mw in reversed(self._mws):
            prev = wrapped
            def _make_wrapper(_mw, _prev):
                async def _w(s):
                    return await _mw.awrap_tool_call(s, context, _prev)
                return _w
            wrapped = _make_wrapper(mw, prev)
        return await wrapped(state)

    async def run_awrap_model_call(self, state: dict, context, handler) -> Any:
        wrapped = handler
        for mw in reversed(self._mws):
            prev = wrapped
            def _make_wrapper(_mw, _prev):
                async def _w(s):
                    return await _mw.awrap_model_call(s, context, _prev)
                return _w
            wrapped = _make_wrapper(mw, prev)
        return await wrapped(state)
