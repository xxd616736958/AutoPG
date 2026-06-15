"""
Core agent query loop — LangGraph StateGraph with astream_events.
"""
import json, os, uuid, asyncio
from typing import Optional, Callable
from datetime import datetime
from langchain_core.messages import (
    BaseMessage, HumanMessage, AIMessage, ToolMessage, SystemMessage,
)
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from .state import AgentState, create_initial_state
from .system_prompt import build_system_prompt, get_user_context, get_system_context
from ..utils.session import save_session, enqueue_write, _serialize, flush_session_now
from ..context.compact import CompactManager
from ..utils.file_cache import FileStateCache, memoized


class QueryEngine:
    """QueryEngine — LangGraph-powered agent loop matching Claude Code's query.ts."""

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
        on_stream_token: Optional[Callable[[str], None]] = None,
        on_tool_start: Optional[Callable[[str, str], None]] = None,
        on_tool_end: Optional[Callable[[str, str], None]] = None,
    ):
        self.tools = tools; self.model_name = model_name
        self.fallback_model = fallback_model; self.cwd = cwd
        self.max_turns = max_turns; self.max_budget_usd = max_budget_usd
        self.permission_mode = permission_mode
        self.custom_system_prompt = custom_system_prompt
        self.append_system_prompt = append_system_prompt
        self.is_non_interactive_session = is_non_interactive_session
        self.provider = provider; self.api_key = api_key; self.base_url = base_url
        self.on_stream_token = on_stream_token
        self.on_tool_start = on_tool_start
        self.on_tool_end = on_tool_end

        self.mutable_messages: list = initial_messages or []
        self.permission_denials: list = []
        self.total_usage = {"input_tokens": 0, "output_tokens": 0}
        self._abort = False
        self._session_id = str(uuid.uuid4())
        self._auto_save = True
        self._compact = CompactManager(model_name=model_name)
        self._graph = None
        self._file_cache = FileStateCache(max_entries=100, max_size_bytes=25 * 1024 * 1024)
        self._result_temp_dir = os.path.join(os.path.expanduser("~/.db-claude"), "tool_results")

    def interrupt(self): self._abort = True

    @property
    def session_id(self) -> str: return self._session_id

    def set_session_id(self, sid: str):
        self._session_id = sid
        self._graph = None  # Invalidate cached graph — new session needs new checkpointer

    async def _get_system_prompt(self) -> str:
        parts = await build_system_prompt(
            tools=self.tools, model=self.model_name, cwd=self.cwd,
            custom_system_prompt=self.custom_system_prompt,
            append_system_prompt=self.append_system_prompt,
        )
        return "\n\n".join(p for p in parts if p)

    def _tools_to_langchain(self) -> list:
        return [t.get_langchain_tool() for t in self.tools if t.is_enabled()]

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

    def _get_graph(self, event_queue: asyncio.Queue = None):
        """Build LangGraph StateGraph. event_queue bridges tool events from
        graph internals to submit_message generator for interleaved streaming."""
        if event_queue is None and self._graph is not None:
            return self._graph

        llm = self._build_llm()
        lc_tools = self._tools_to_langchain()
        tool_map = {t.name: t for t in lc_tools}
        llm_with_tools = llm.bind_tools(lc_tools)

        workflow = StateGraph(AgentState)

        # ── Node: call model ──
        async def call_model(state: AgentState) -> dict:
            if state.get("abort_signal") or self._abort:
                return {"should_continue": False}

            messages = list(state.get("messages", []))
            sys_msg = SystemMessage(content=state.get("system_prompt", ""))
            full_messages = [sys_msg] + messages

            response = await llm_with_tools.ainvoke(full_messages)

            # Track usage
            self._track_usage(response)
            usage = dict(state.get("total_usage", {}))
            usage.update(self.total_usage)

            stop_reason = None
            if hasattr(response, "response_metadata") and response.response_metadata:
                finish = response.response_metadata.get("finish_reason", "")
                stop_reason = "tool_use" if finish == "tool_calls" else ("end_turn" if finish == "stop" else None)

            return {
                "messages": [response],
                "total_usage": usage,
                "last_stop_reason": stop_reason,
            }

        # ── Node: execute tools ──
        async def execute_tools(state: AgentState) -> dict:
            messages = list(state.get("messages", []))
            if not messages: return {"should_continue": False}

            last_msg = messages[-1]
            if not isinstance(last_msg, AIMessage): return {"should_continue": False}

            tool_calls = list(getattr(last_msg, "tool_calls", []) or [])
            if not tool_calls: return {"should_continue": False}

            tool_messages = []
            for tc in tool_calls:
                if self._abort: break
                tool_name = tc.get("name", "")
                tool_args = tc.get("args", {})
                tool_call_id = tc.get("id", str(uuid.uuid4()))

                native_tool = None
                for t in self.tools:
                    if t.name == tool_name or tool_name in (t.aliases or []):
                        native_tool = t; break

                # Notify tool start via event bridge
                call_display = native_tool.format_call(tool_args) if native_tool else tool_name
                activity = native_tool.get_activity_description(tool_args) if native_tool else tool_name
                if event_queue is not None:
                    event_queue.put_nowait({"type": "tool_start", "name": tool_name, "args": tool_args, "call_display": call_display, "activity": activity})

                if native_tool:
                    try:
                        ctx = {"cwd": self.cwd, "permission_mode": self.permission_mode}
                        result = await native_tool.call(tool_args, ctx)
                        result_data = result.get("data", result) if isinstance(result, dict) else result
                        content = json.dumps(result_data, ensure_ascii=False, indent=2) if not isinstance(result_data, str) else result_data
                    except Exception as e:
                        content = f"Error: {str(e)}"

                    # ── Tool result budget (Claude Code: maxResultSizeChars) ──
                    max_chars = getattr(native_tool, "max_result_chars", 50_000)
                    if max_chars != float("inf") and len(content) > max_chars:
                        os.makedirs(self._result_temp_dir, exist_ok=True)
                        result_file = os.path.join(self._result_temp_dir, f"result_{tool_call_id[:12]}.txt")
                        try:
                            with open(result_file, "w", encoding="utf-8") as f:
                                f.write(content)
                            content = (
                                f"[Tool result too large ({len(content):,} chars > {max_chars:,} limit). "
                                f"Full content saved to {result_file}. Preview (first 500 chars):\n"
                                f"{content[:500]}...\n\n"
                                f"Use Read to access the full result if needed."
                            )
                        except Exception:
                            content = content[:max_chars] + f"\n...[truncated at {max_chars} chars]"
                else:
                    lc_tool = tool_map.get(tool_name)
                    if lc_tool:
                        try:
                            r = await lc_tool.ainvoke(tool_args)
                            content = json.dumps(r, ensure_ascii=False, indent=2) if not isinstance(r, str) else r
                        except Exception as e:
                            content = f"Error: {str(e)}"
                    else:
                        content = f"Tool '{tool_name}' not found"

                # Notify tool end via event bridge
                try:
                    fmt_data = json.loads(content) if content.startswith("{") else content
                except:
                    fmt_data = content
                formatted = native_tool.format_result(fmt_data) if native_tool else content[:200]
                if event_queue is not None:
                    event_queue.put_nowait({"type": "tool_end", "name": tool_name, "result_preview": formatted})

                tool_messages.append(ToolMessage(
                    content=str(content), tool_call_id=tool_call_id, name=tool_name,
                ))

            turn_count = state.get("turn_count", 0) + 1
            max_t = state.get("max_turns")
            return {
                "messages": tool_messages, "turn_count": turn_count,
                "should_continue": not (max_t and turn_count > max_t),
            }

        # ── Router ──
        def router(state: AgentState) -> str:
            if state.get("abort_signal") or self._abort: return "end"
            if not state.get("should_continue", True): return "end"
            msgs = state.get("messages", [])
            if not msgs: return "end"
            last = msgs[-1]
            if isinstance(last, AIMessage):
                tc = getattr(last, "tool_calls", None)
                if tc and len(tc) > 0:
                    max_t = state.get("max_turns")
                    if max_t and state.get("turn_count", 0) >= max_t: return "end"
                    return "tools"
            return "end"

        workflow.add_node("agent", call_model)
        workflow.add_node("tools", execute_tools)
        workflow.set_entry_point("agent")
        workflow.add_conditional_edges("agent", router, {"tools": "tools", "end": END})
        workflow.add_edge("tools", "agent")

        # MemorySaver — within-run state. Cross-session persistence handled by
        # utils/session.py (JSON files in ~/.db-claude/sessions/).
        # On /resume, messages are restored into mutable_messages before graph runs.
        checkpointer = MemorySaver()
        self._graph = workflow.compile(checkpointer=checkpointer)
        return self._graph

    async def submit_message(self, prompt: str, options: dict = None):
        """Submit message using LangGraph with streaming via token-level astream_events."""
        start_time = datetime.now()
        sys_prompt = await self._get_system_prompt()

        user_msg = HumanMessage(content=prompt)
        self.mutable_messages.append(user_msg)

        # ── Write user message BEFORE API call ──
        # Claude Code pattern: write now so --resume works even if process
        # is killed during the API call. Fire-and-forget for responsiveness.
        enqueue_write(self._session_id, _serialize(user_msg))

        initial_state = create_initial_state(
            messages=list(self.mutable_messages),
            system_prompt=sys_prompt,
            user_context=await get_user_context(),
            system_context=await get_system_context(),
            tools=self._tools_to_langchain(),
            model=self.model_name, fallback_model=self.fallback_model,
            max_turns=self.max_turns, cwd=self.cwd,
            permission_mode=self.permission_mode,
            is_non_interactive_session=self.is_non_interactive_session,
        )

        # Event bridge: asyncio.Queue for interleaving tool events with token streaming
        event_queue: asyncio.Queue = asyncio.Queue()

        try:
            app = self._get_graph(event_queue)
            config = {"configurable": {"thread_id": self._session_id}}

            accumulated_text = ""
            turn_count = 0

            # Stream tokens, draining tool events concurrently
            async for event in app.astream_events(
                {"messages": list(initial_state.get("messages", []))},
                config=config, version="v2",
            ):
                if self._abort: break
                kind = event.get("event", "")

                if kind == "on_chat_model_stream":
                    # Drain any pending tool events first
                    while not event_queue.empty():
                        try:
                            te = event_queue.get_nowait()
                            yield te
                            if te["type"] == "tool_start" and self.on_tool_start:
                                self.on_tool_start(te["name"], te.get("activity", ""))
                            elif te["type"] == "tool_end" and self.on_tool_end:
                                self.on_tool_end(te["name"], te.get("result_preview", ""))
                        except asyncio.QueueEmpty:
                            break

                    chunk = event.get("data", {}).get("chunk")
                    if chunk and hasattr(chunk, "content") and chunk.content:
                        token = chunk.content
                        if isinstance(token, str) and token:
                            accumulated_text += token
                            yield {"type": "token", "content": token}
                            if self.on_stream_token:
                                self.on_stream_token(token)

                elif kind == "on_chain_end" and event.get("name") in ("agent", "tools"):
                    turn_count += 1

            # Drain remaining tool events
            while not event_queue.empty():
                try:
                    te = event_queue.get_nowait()
                    yield te
                except asyncio.QueueEmpty:
                    break

            # ── Done ──
            # Pull final state from LangGraph checkpointer to get ALL messages
            final_state = app.get_state(config)
            if final_state and hasattr(final_state, 'values'):
                all_messages = list(final_state.values.get("messages", []))
                if all_messages:
                    self.mutable_messages = all_messages

            text_result = accumulated_text.strip()
            if not text_result:
                for msg in reversed(self.mutable_messages):
                    if isinstance(msg, AIMessage) and msg.content:
                        text_result = str(msg.content)
                        break

            if self._auto_save and self.mutable_messages:
                # Flush pending deferred writes, then write full transcript
                flush_session_now(self._session_id)
                save_session(self._session_id, self.mutable_messages, metadata={
                    "model": self.model_name, "provider": self.provider,
                    "cwd": self.cwd, "usage": self.total_usage,
                })

            duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
            yield {
                "type": "result", "subtype": "success", "is_error": False,
                "duration_ms": duration_ms, "num_turns": turn_count,
                "result": text_result, "stop_reason": "end_turn",
                "session_id": self._session_id, "usage": self.total_usage,
                "permission_denials": self.permission_denials,
            }
        except Exception as e:
            duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
            yield {
                "type": "result", "subtype": "error_during_execution", "is_error": True,
                "duration_ms": duration_ms, "result": "",
                "session_id": self._session_id, "usage": self.total_usage,
                "errors": [str(e)],
            }

    def _track_usage(self, response):
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            um = response.usage_metadata
            self.total_usage["input_tokens"] += um.get("input_tokens", 0)
            self.total_usage["output_tokens"] += um.get("output_tokens", 0)
        elif hasattr(response, "response_metadata") and response.response_metadata:
            rm = response.response_metadata
            tu = rm.get("token_usage", {})
            self.total_usage["input_tokens"] += tu.get("prompt_tokens", 0)
            self.total_usage["output_tokens"] += tu.get("completion_tokens", 0)
