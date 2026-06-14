"""
Core agent query loop for db-claude.
Architecturally mirrors Claude Code's query.ts while(true) loop.
Supports: streaming tokens, tool progress, session persistence, auto-compact.
"""
import json, os, uuid
from typing import Optional, Callable
from datetime import datetime
from langchain_core.messages import (
    BaseMessage, HumanMessage, AIMessage, ToolMessage, SystemMessage,
)
from .state import AgentState, create_initial_state
from .system_prompt import build_system_prompt, get_user_context, get_system_context
from ..utils.session import save_session
from ..context.compact import CompactManager


class QueryEngine:
    """QueryEngine — mirrors Claude Code's QueryEngine + query.ts loop."""

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

    def interrupt(self): self._abort = True

    @property
    def session_id(self) -> str: return self._session_id

    def set_session_id(self, sid: str): self._session_id = sid

    async def _get_system_prompt(self) -> str:
        parts = await build_system_prompt(
            tools=self.tools, model=self.model_name, cwd=self.cwd,
            custom_system_prompt=self.custom_system_prompt,
            append_system_prompt=self.append_system_prompt,
        )
        return "\n\n".join(p for p in parts if p)

    async def submit_message(self, prompt: str, options: dict = None):
        """
        Submit a message. Yields: {"type":"token","content":"..."}
        | {"type":"tool_start","name":"...","activity":"..."}
        | {"type":"tool_end","name":"...","result_preview":"..."} | {"type":"result",...}
        """
        start_time = datetime.now()
        sys_prompt = await self._get_system_prompt()

        self.mutable_messages.append(HumanMessage(content=prompt))
        turn_count = 0

        try:
            accumulated_text = ""

            # Main loop — mirrors query.ts while(true)
            while True:
                if self._abort:
                    break

                # Build messages for API call
                sys_msg = SystemMessage(content=sys_prompt)
                api_messages = [sys_msg] + list(self.mutable_messages)

                # Estimate input tokens for tracking
                input_text = sys_prompt + " ".join(
                    str(m.content) if hasattr(m, "content") else ""
                    for m in self.mutable_messages[-20:]  # Last 20 messages for efficiency
                )

                # ── Call model with streaming ──
                llm = self._build_llm()
                lc_tools = self._tools_to_langchain()
                llm_with_tools = llm.bind_tools(lc_tools)
                tool_map = {t.name: t for t in lc_tools}

                full_content = ""
                full_response = None
                # Accumulate tool calls from streaming chunks
                accumulated_tool_calls: dict[int, dict] = {}  # index → {name, id, args_str}

                async for chunk in llm_with_tools.astream(api_messages):
                    if self._abort:
                        break
                    full_response = chunk
                    token = getattr(chunk, "content", "")
                    if isinstance(token, str) and token:
                        full_content += token
                        yield {"type": "token", "content": token}
                        accumulated_text += token
                        if self.on_stream_token:
                            self.on_stream_token(token)

                    # Accumulate tool calls from chunks
                    tc_chunks = getattr(chunk, "tool_call_chunks", None) or []
                    for tcc in tc_chunks:
                        idx = tcc.get("index", 0)
                        if idx not in accumulated_tool_calls:
                            accumulated_tool_calls[idx] = {"name": "", "id": "", "args_str": ""}
                        if tcc.get("name"):
                            accumulated_tool_calls[idx]["name"] = tcc["name"]
                        if tcc.get("id"):
                            accumulated_tool_calls[idx]["id"] = tcc["id"]
                        if tcc.get("args"):
                            accumulated_tool_calls[idx]["args_str"] += tcc["args"]

                if self._abort or full_response is None:
                    break

                # Build tool_calls from accumulated chunks
                tool_calls = []
                for idx in sorted(accumulated_tool_calls.keys()):
                    tc_data = accumulated_tool_calls[idx]
                    if tc_data["name"]:
                        try:
                            args = json.loads(tc_data["args_str"]) if tc_data["args_str"] else {}
                        except json.JSONDecodeError:
                            args = {}
                        tool_calls.append({
                            "name": tc_data["name"],
                            "args": args,
                            "id": tc_data["id"] or str(uuid.uuid4()),
                            "type": "tool_call",
                        })

                # Also check full_response.tool_calls (non-streaming fallback)
                if not tool_calls:
                    tool_calls = list(getattr(full_response, "tool_calls", []) or [])

                # Build proper AIMessage
                ai_msg = AIMessage(
                    content=full_content,
                    additional_kwargs=getattr(full_response, "additional_kwargs", {}),
                    response_metadata=getattr(full_response, "response_metadata", {}),
                    id=getattr(full_response, "id", None),
                    tool_calls=tool_calls,
                )
                self.mutable_messages.append(ai_msg)

                # Track usage with input + output text for estimation
                self._track_usage(full_response, input_text=input_text, output_text=full_content)

                # ── Check for tool calls ──
                if not tool_calls:
                    break  # No tools → done

                turn_count += 1
                if self.max_turns and turn_count > self.max_turns:
                    break

                # ── Execute tools ──
                for tc_item in tool_calls:
                    if self._abort:
                        break
                    tool_name = tc_item.get("name", "")
                    tool_args = tc_item.get("args", {})
                    tool_call_id = tc_item.get("id", str(uuid.uuid4()))

                    # Find native tool for activity description
                    native_tool = None
                    for t in self.tools:
                        if t.name == tool_name or tool_name in (t.aliases or []):
                            native_tool = t
                            break
                    activity = native_tool.get_activity_description(tool_args) if native_tool else tool_name

                    # Format call for Claude Code display
                    call_display = native_tool.format_call(tool_args) if native_tool else f"{tool_name}"
                    yield {"type": "tool_start", "name": tool_name, "activity": activity, "args": tool_args, "call_display": call_display}
                    if self.on_tool_start:
                        self.on_tool_start(tool_name, activity)

                    # Execute tool
                    if native_tool:
                        try:
                            ctx = {"cwd": self.cwd, "permission_mode": self.permission_mode}
                            result = await native_tool.call(tool_args, ctx)
                            result_data = result.get("data", result) if isinstance(result, dict) else result
                            content = json.dumps(result_data, ensure_ascii=False, indent=2) if not isinstance(result_data, str) else result_data
                        except Exception as e:
                            content = f"Error: {str(e)}"
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

                    # Format result using tool's format_result for Claude Code style
                    result_data_for_format = None
                    try:
                        result_data_for_format = json.loads(content) if content.startswith("{") else content
                    except: result_data_for_format = content
                    formatted_result = native_tool.format_result(result_data_for_format) if native_tool else content[:200]

                    yield {"type": "tool_end", "name": tool_name, "result_preview": formatted_result}
                    if self.on_tool_end:
                        self.on_tool_end(tool_name, formatted_result)

                    self.mutable_messages.append(ToolMessage(
                        content=str(content), tool_call_id=tool_call_id, name=tool_name,
                    ))

            # ── Done ──
            text_result = accumulated_text.strip()
            if not text_result:
                for msg in reversed(self.mutable_messages):
                    if isinstance(msg, AIMessage) and msg.content:
                        text_result = str(msg.content)
                        break

            # Auto-save session
            if self._auto_save and self.mutable_messages:
                save_session(self._session_id, self.mutable_messages, metadata={
                    "model": self.model_name, "provider": self.provider,
                    "cwd": self.cwd, "usage": self.total_usage,
                })

            duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
            yield {
                "type": "result", "subtype": "success", "is_error": False,
                "duration_ms": duration_ms, "num_turns": turn_count,
                "result": text_result, "stop_reason": "end_turn" if text_result else "tool_use",
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

    def _track_usage(self, response, input_text: str = "", output_text: str = ""):
        # Try usage_metadata first (available on non-streaming Anthropic/OpenAI)
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            um = response.usage_metadata
            self.total_usage["input_tokens"] += um.get("input_tokens", 0)
            self.total_usage["output_tokens"] += um.get("output_tokens", 0)
            return
        # Try response_metadata.token_usage (some OpenAI-compatible providers)
        if hasattr(response, "response_metadata") and response.response_metadata:
            rm = response.response_metadata
            tu = rm.get("token_usage", {})
            if tu:
                self.total_usage["input_tokens"] += tu.get("prompt_tokens", 0)
                self.total_usage["output_tokens"] += tu.get("completion_tokens", 0)
                return
        # Fallback: count ourselves using the compact manager's tokenizer
        if input_text:
            self.total_usage["input_tokens"] += self._compact.count_tokens(input_text)
        if output_text:
            self.total_usage["output_tokens"] += self._compact.count_tokens(output_text)
