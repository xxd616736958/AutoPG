"""
QueryEngine — assembles clean business graph + middleware stack.
"""
import os, uuid, asyncio, time
from typing import Optional, Callable
from datetime import datetime
from langchain_core.messages import HumanMessage, AIMessage

from .graph import build_agent_graph
from .system_prompt import build_system_prompt
from .state import create_initial_state
from ..utils.session import save_session, enqueue_write, _serialize
from ..utils.file_cache import FileStateCache
from ..context.compact import CompactManager
from ..context.collapse import ContextCollapseManager
from ..middleware import (
    MiddlewareStack,
    ContextCollapseMiddleware, AutoCompactMiddleware,
    PermissionCheckMiddleware, FileCacheMiddleware,
    SessionPersistenceMiddleware, ProjectContextMiddleware,
    TokenTrackingMiddleware,
)


# ── Default middleware stack (all cross-cutting concerns) ──

def _build_default_stack(session_id: str, provider: str, api_key: str, base_url: str):
    return MiddlewareStack([
        ProjectContextMiddleware(),
        ContextCollapseMiddleware(),
        AutoCompactMiddleware(),
        PermissionCheckMiddleware(),
        FileCacheMiddleware(),
        TokenTrackingMiddleware(),
        SessionPersistenceMiddleware(),
    ])


class QueryEngine:
    """QueryEngine — thin shell over business graph + middleware stack."""

    def __init__(
        self, tools: list, model_name: str = "claude-sonnet-4-6",
        fallback_model: Optional[str] = None, cwd: str = "",
        max_turns: Optional[int] = None, max_budget_usd: Optional[float] = None,
        permission_mode: str = "default",
        custom_system_prompt: Optional[str] = None,
        append_system_prompt: Optional[str] = None,
        is_non_interactive_session: bool = False,
        initial_messages: Optional[list] = None,
        provider: str = "anthropic",
        api_key: Optional[str] = None, base_url: Optional[str] = None,
        on_stream_token: Optional[Callable] = None,
        on_tool_start: Optional[Callable] = None,
        on_tool_end: Optional[Callable] = None,
        on_permission_check: Optional[Callable] = None,
    ):
        self.tools = tools; self.model_name = model_name
        self.fallback_model = fallback_model; self.cwd = cwd
        self.max_turns = max_turns
        self.permission_mode = permission_mode
        self.custom_system_prompt = custom_system_prompt
        self.append_system_prompt = append_system_prompt
        self.is_non_interactive_session = is_non_interactive_session
        self.provider = provider; self.api_key = api_key; self.base_url = base_url
        self.on_stream_token = on_stream_token
        self.on_tool_start = on_tool_start
        self.on_tool_end = on_tool_end
        self.on_permission_check = on_permission_check

        self._session_id = str(uuid.uuid4())
        self.mutable_messages: list = initial_messages or []
        self.total_usage = {"input_tokens": 0, "output_tokens": 0}
        self._abort = False
        self._auto_save = True
        self._child_engines: list = []

        # Infrastructure
        self._file_cache = FileStateCache(100, 25 * 1024 * 1024)
        self._compact = CompactManager(model_name, provider, api_key, base_url)
        self._collapse = ContextCollapseManager(self._session_id, provider, api_key, base_url)
        self._result_temp_dir = os.path.join(os.path.expanduser("~/.db-claude"), "tool_results")

        # Middleware stack
        self._stack = _build_default_stack(self._session_id, provider, api_key, base_url)

        # Graph (cached after first build)
        self._graph = None

    def interrupt(self):
        self._abort = True
        for c in self._child_engines:
            c.interrupt()

    @property
    def session_id(self) -> str:
        return self._session_id

    def set_session_id(self, sid: str):
        self._session_id = sid
        self._collapse = ContextCollapseManager(sid, self.provider, self.api_key, self.base_url)
        self._stack = _build_default_stack(sid, self.provider, self.api_key, self.base_url)
        self._graph = None  # Invalidate cached graph (holds old middleware)

    def cleanup(self):
        import shutil
        if os.path.exists(self._result_temp_dir):
            try:
                shutil.rmtree(self._result_temp_dir)
            except Exception:
                pass

    def _build_graph(self):
        if self._graph is None:
            self._graph = build_agent_graph(
                llm_builder=self._build_llm,
                tools=self.tools,
                on_stream_token=self.on_stream_token,
                on_tool_start=self.on_tool_start,
                on_tool_end=self.on_tool_end,
                on_permission_check=self.on_permission_check,
                middleware_stack=self._stack,
                file_cache=self._file_cache,
                result_temp_dir=self._result_temp_dir,
            )
        return self._graph

    def _build_llm(self):
        if self.provider == "deepseek":
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(
                model=self.model_name,
                api_key=self.api_key or os.environ.get("DEEPSEEK_API_KEY"),
                base_url=self.base_url or "https://api.deepseek.com/v1",
                temperature=0.7, max_tokens=8192, streaming=True,
            )
        else:
            from langchain_anthropic import ChatAnthropic
            return ChatAnthropic(
                model=self.model_name,
                api_key=self.api_key or os.environ.get("ANTHROPIC_API_KEY"),
                base_url=self.base_url or os.environ.get("ANTHROPIC_BASE_URL"),
                max_tokens=8192, temperature=1.0, streaming=True,
            )

    async def submit_message(self, prompt: str, options: dict = None):
        """Submit message through middleware stack + business graph."""
        start_time = datetime.now()
        sys_prompt = await self._build_sys_prompt()

        self.mutable_messages.append(HumanMessage(content=prompt))
        # Pre-write user message (crash-safe)
        enqueue_write(self._session_id, _serialize(self.mutable_messages[-1]))

        state = create_initial_state(
            messages=list(self.mutable_messages),
            system_prompt=sys_prompt,
            model=self.model_name,
            max_turns=self.max_turns,
            cwd=self.cwd,
            permission_mode=self.permission_mode,
            is_non_interactive_session=self.is_non_interactive_session,
        )

        # ── Runtime context passed to all middleware ──
        runtime = {
            "session_id": self._session_id,
            "model": self.model_name,
            "provider": self.provider,
            "cwd": self.cwd,
            "auto_save": self._auto_save,
            "total_usage": self.total_usage,
            "collapse_manager": self._collapse,
            "compact_manager": self._compact,
            "file_cache": self._file_cache,
            "on_permission_check": self.on_permission_check,
            "result_temp_dir": self._result_temp_dir,
        }

        try:
            # before_agent
            state = await self._stack.run_before_agent(state, runtime)

            # Run graph with streaming, injecting middleware at event boundaries
            graph = self._build_graph()
            config = {"configurable": {"thread_id": self._session_id}}

            accumulated_text = ""
            turn_count = 0

            async for event in graph.astream_events(
                {"messages": list(state.get("messages", []))},
                config=config, version="v2",
            ):
                if self._abort:
                    break
                kind = event.get("event", "")

                if kind == "on_chat_model_start":
                    state = await self._stack.run_before_model(state, runtime)

                elif kind == "on_chat_model_stream":
                    chunk = event.get("data", {}).get("chunk")
                    if chunk and hasattr(chunk, "content") and chunk.content:
                        token = chunk.content
                        if isinstance(token, str) and token:
                            accumulated_text += token
                            yield {"type": "token", "content": token}

                elif kind == "on_chat_model_end":
                    runtime["_last_model_response"] = event.get("data", {}).get("output")
                    state = await self._stack.run_after_model(state, runtime)

                elif kind == "on_tool_start":
                    name = event.get("name", "")
                    tool_input = event.get("data", {}).get("input", {})
                    native = None
                    for t in self.tools:
                        if t.name == name or name in (t.aliases or []):
                            native = t; break
                    call_display = native.format_call(tool_input) if native else name
                    yield {"type": "tool_start", "name": name, "call_display": call_display}

                elif kind == "on_tool_end":
                    output = event.get("data", {}).get("output")
                    result_str = str(output.content) if output and hasattr(output, "content") else "done"
                    native = None
                    for t in self.tools:
                        if t.name == event.get("name", ""):
                            native = t; break
                    try:
                        import json
                        fmt = json.loads(result_str) if result_str.startswith("{") else result_str
                    except Exception:
                        fmt = result_str
                    formatted = native.format_result(fmt) if native else result_str[:200]
                    yield {"type": "tool_end", "name": event.get("name", ""), "result_preview": formatted}

                elif kind == "on_chain_end" and event.get("name") == "tools":
                    turn_count += 1

            # Extract final state from graph
            final_state = graph.get_state(config)
            if final_state and hasattr(final_state, "values"):
                self.mutable_messages = list(final_state.values.get("messages", []))

            # after_agent
            state = await self._stack.run_after_agent(state, runtime)

            text_result = accumulated_text.strip()
            if not text_result:
                for msg in reversed(self.mutable_messages):
                    if isinstance(msg, AIMessage) and msg.content:
                        text_result = str(msg.content)
                        break

            duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
            yield {
                "type": "result", "subtype": "success", "is_error": False,
                "duration_ms": duration_ms, "num_turns": turn_count,
                "result": text_result,
                "session_id": self._session_id, "usage": self.total_usage,
            }
        except Exception as e:
            duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
            yield {
                "type": "result", "subtype": "error_during_execution", "is_error": True,
                "duration_ms": duration_ms, "result": "",
                "session_id": self._session_id, "usage": self.total_usage,
                "errors": [str(e)],
            }

    async def _build_sys_prompt(self) -> str:
        parts = await build_system_prompt(
            tools=self.tools, model=self.model_name, cwd=self.cwd,
            custom_system_prompt=self.custom_system_prompt,
            append_system_prompt=self.append_system_prompt,
        )
        return "\n\n".join(p for p in parts if p)
