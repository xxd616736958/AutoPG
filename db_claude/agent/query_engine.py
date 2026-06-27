"""
QueryEngine — thin shell over compiled graph. ToolNode handles events.
"""
import os, uuid, time, asyncio, logging
from typing import Optional, Callable
from datetime import datetime
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

logger = logging.getLogger(__name__)

from ..graph import build_agent_graph
from ..context_schema import AgentContext
from ..context.compact import CompactManager
from ..context.collapse import ContextCollapseManager
from ..middleware import MiddlewareStack, SessionPersistenceMiddleware
from ..utils.file_cache import FileStateCache
from ..utils.session import enqueue_write, _serialize
from ..tools.display import format_call, format_result
from .system_prompt import build_system_prompt


def _default_middleware_stack() -> MiddlewareStack:
    from ..middleware import (
        ContextCollapseMiddleware, AutoCompactMiddleware,
        PermissionCheckMiddleware, FileCacheMiddleware,
        ToolResultBudgetMiddleware, TokenTrackingMiddleware,
        ProjectContextMiddleware, UserHookMiddleware,
    )
    from ..utils.hooks import load_hooks_config
    hooks = load_hooks_config()
    return MiddlewareStack([
        ProjectContextMiddleware(),
        UserHookMiddleware(hooks),
        ContextCollapseMiddleware(),
        AutoCompactMiddleware(),
        PermissionCheckMiddleware(),
        FileCacheMiddleware(),
        ToolResultBudgetMiddleware(),
        TokenTrackingMiddleware(),
        SessionPersistenceMiddleware(),
    ]), hooks


class QueryEngine:
    """Runs compiled graph with middleware stack. Event bridge to CLI/REPL."""

    def __init__(
        self, tools: list, model_name: str = "deepseek-v4-flash",
        fallback_model: str = None, cwd: str = "", max_turns: int = None,
        max_budget_usd: float = None, permission_mode: str = "default",
        custom_system_prompt: str = None, append_system_prompt: str = None,
        is_non_interactive_session: bool = False,
        initial_messages: list = None,
        provider: str = "deepseek", api_key: str = None, base_url: str = None,
        on_stream_token: Callable = None, on_tool_start: Callable = None,
        on_tool_end: Callable = None, on_permission_check: Callable = None,
    ):
        self.tools = tools; self.model_name = model_name
        self.cwd = cwd; self.provider = provider
        self.api_key = api_key; self.base_url = base_url
        self.max_turns = max_turns or 100
        self.permission_mode = permission_mode
        self.custom_system_prompt = custom_system_prompt
        self.append_system_prompt = append_system_prompt
        self.is_non_interactive = is_non_interactive_session
        self.on_stream_token = on_stream_token
        self.on_tool_start = on_tool_start
        self.on_tool_end = on_tool_end
        self.on_permission_check = on_permission_check

        self._session_id = str(uuid.uuid4())
        self.mutable_messages: list = initial_messages or []
        self.total_usage = {"input_tokens": 0, "output_tokens": 0}
        self._abort = False; self._auto_save = True
        self._child_engines: list = []

        self._file_cache = FileStateCache(100, 25*1024*1024)
        self._compact = CompactManager(model_name, provider, api_key, base_url)
        self._collapse = ContextCollapseManager(self._session_id, provider, api_key, base_url)
        self._result_temp_dir = os.path.join(os.path.expanduser("~/.db-claude"), "tool_results")
        self._stack, self._hooks_config = _default_middleware_stack()
        self._graph = None; self._sys_prompt_cache = ""

    def interrupt(self):
        self._abort = True
        for c in self._child_engines: c.interrupt()

    @property
    def session_id(self): return self._session_id

    def set_session_id(self, sid: str):
        self._session_id = sid
        self._collapse = ContextCollapseManager(sid, self.provider, self.api_key, self.base_url)
        self._graph = None

    def cleanup(self):
        import shutil
        if os.path.exists(self._result_temp_dir):
            shutil.rmtree(self._result_temp_dir, ignore_errors=True)

    def _get_graph(self, hooks_config: dict = None):
        # Rebuild if hooks changed (user edited config.json between turns)
        if hooks_config and hooks_config != getattr(self, '_last_hooks', None):
            self._graph = None
            self._last_hooks = dict(hooks_config)
        if self._graph is None:
            self._graph = build_agent_graph(
                tools=self.tools, model=self.model_name,
                middleware_stack=self._stack,
                provider=self.provider, api_key=self.api_key, base_url=self.base_url,
                system_prompt=self._sys_prompt_cache, max_turns=self.max_turns,
                hooks_config_param=self._hooks_config,
            )
        return self._graph

    async def _ensure_sys_prompt(self):
        if not self._sys_prompt_cache:
            parts = await build_system_prompt(
                tools=self.tools, model=self.model_name, cwd=self.cwd,
                custom_system_prompt=self.custom_system_prompt,
                append_system_prompt=self.append_system_prompt,
            )
            self._sys_prompt_cache = "\n\n".join(p for p in parts if p)

    def _drop_incomplete_trailing_tool_turn(self):
        """Remove assistant tool-call messages that do not have matching ToolMessages.

        OpenAI-compatible APIs reject any history where an AIMessage with
        tool_calls is not followed by one ToolMessage for every tool_call_id.
        This can happen if a prior turn crashed while formatting/displaying a
        tool event before the ToolNode completed.
        """
        cleaned = []
        msgs = list(self.mutable_messages)
        i = 0
        changed = False
        while i < len(msgs):
            msg = msgs[i]
            if isinstance(msg, AIMessage) and (getattr(msg, "tool_calls", None) or []):
                tool_calls = getattr(msg, "tool_calls", None) or []
                required = [tc.get("id") for tc in tool_calls if tc.get("id")]
                j = i + 1
                following_tools = []
                while j < len(msgs) and isinstance(msgs[j], ToolMessage):
                    following_tools.append(msgs[j])
                    j += 1
                seen = {getattr(m, "tool_call_id", None) for m in following_tools}
                if required and set(required).issubset(seen):
                    cleaned.append(msg)
                    cleaned.extend(following_tools)
                else:
                    changed = True
                i = j
                continue
            cleaned.append(msg)
            i += 1
        if changed:
            self.mutable_messages = cleaned
            self._graph = None

    async def submit_message(self, prompt: str, options: dict = None):
        start_time = datetime.now()
        await self._ensure_sys_prompt()
        logger.info("submit_start session=%s prompt_len=%d", self._session_id[:8], len(prompt))

        self._drop_incomplete_trailing_tool_turn()
        user_msg = HumanMessage(content=prompt)
        self.mutable_messages.append(user_msg)
        enqueue_write(self._session_id, _serialize(user_msg))

        context = AgentContext(
            session_id=self._session_id, cwd=self.cwd,
            provider=self.provider, model=self.model_name,
            permission_mode=self.permission_mode, auto_save=self._auto_save,
            is_non_interactive=self.is_non_interactive,
            max_turns=self.max_turns,
            collapse_manager=self._collapse, compact_manager=self._compact,
            file_cache=self._file_cache, total_usage=self.total_usage,
            result_temp_dir=self._result_temp_dir, _parent_engine=self,
            on_stream_token=self.on_stream_token,
            on_tool_start=self.on_tool_start,
            on_tool_end=self.on_tool_end,
            on_permission_check=self.on_permission_check,
        )

        graph = self._get_graph(self._hooks_config)
        config = {
            "configurable": {"thread_id": self._session_id, "_context": context},
            "recursion_limit": max(50, self.max_turns * 3),
        }

        try:
            accumulated_text = ""; turn_count = 0

            async for event in graph.astream_events(
                {"messages": list(self.mutable_messages),
                 "system_prompt": self._sys_prompt_cache},
                config=config, version="v2",
            ):
                if self._abort: break
                kind = event.get("event", "")

                if kind == "on_chat_model_stream":
                    chunk = event.get("data", {}).get("chunk")
                    if chunk and hasattr(chunk, "content") and chunk.content:
                        token = str(chunk.content)
                        accumulated_text += token
                        yield {"type": "token", "content": token}

                elif kind == "on_tool_start":
                    name = event.get("name", "")
                    inp = event.get("data", {}).get("input", {})
                    yield {"type": "tool_start", "name": name,
                           "call_display": format_call(name, inp)}

                elif kind == "on_tool_end":
                    name = event.get("name", "")
                    output = event.get("data", {}).get("output")
                    result_str = str(getattr(output, "content", "done"))
                    preview = format_result(name, result_str)
                    # Read hook output from side channel
                    hook_part = ""
                    try:
                        from ..graph import drain_hook_outputs
                        hook_part = drain_hook_outputs()
                    except Exception: pass
                    if hook_part:
                        preview = f"{preview}\n{hook_part}"
                    yield {"type": "tool_end", "name": name,
                           "result_preview": preview}

                elif kind == "on_chain_end" and event.get("name") == "tools":
                    turn_count += 1

            final = graph.get_state(config)
            if final and hasattr(final, "values"):
                self.mutable_messages = list(final.values.get("messages", []))
            self.total_usage = context.total_usage

            text_result = accumulated_text.strip()
            if not text_result:
                for msg in reversed(self.mutable_messages):
                    if isinstance(msg, AIMessage) and msg.content:
                        text_result = str(msg.content); break

            duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
            logger.info("submit_done session=%s turns=%d duration=%dms tokens_in=%d tokens_out=%d",
                        self._session_id[:8], turn_count, duration_ms,
                        self.total_usage.get("input_tokens", 0), self.total_usage.get("output_tokens", 0))
            yield {"type": "result", "subtype": "success", "is_error": False,
                   "duration_ms": duration_ms, "num_turns": turn_count,
                   "result": text_result, "session_id": self._session_id,
                   "usage": self.total_usage}
        except Exception as e:
            duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
            logger.exception("submit_error session=%s duration=%dms", self._session_id[:8], duration_ms)
            yield {"type": "result", "subtype": "error_during_execution", "is_error": True,
                   "duration_ms": duration_ms, "result": "",
                   "session_id": self._session_id, "usage": self.total_usage,
                   "errors": [str(e)]}

    def _find_tool(self, name: str):
        for t in self.tools:
            aliases = getattr(t, "aliases", []) or []
            if t.name == name or name in aliases: return t
        return None
