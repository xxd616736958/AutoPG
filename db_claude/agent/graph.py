"""
Pure business StateGraph — call model, execute tools, route.
All cross-cutting concerns extracted to middleware.
"""
import json, os, uuid, asyncio
from typing import Optional, Callable
from langchain_core.messages import AIMessage, ToolMessage, SystemMessage
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from .state import AgentState


def build_agent_graph(
    llm_builder: Callable,
    tools: list,
    *,
    on_stream_token: Optional[Callable] = None,
    on_tool_start: Optional[Callable] = None,
    on_tool_end: Optional[Callable] = None,
    on_permission_check: Optional[Callable] = None,
    file_cache=None,
    result_temp_dir: str = "",
) -> 'CompiledStateGraph':
    """
    Build a clean business-only StateGraph.
    call_model → router → (tools → call_model | end)

    All cross-cutting logic (collapse, compact, budget, cache, tracking)
    lives in middleware. Nodes here are pure: input state → output delta.
    """
    lc_tools = [t.get_langchain_tool() for t in tools if t.is_enabled()]
    tool_map = {t.name: t for t in lc_tools}
    llm_with_tools = llm_builder().bind_tools(lc_tools)

    workflow = StateGraph(AgentState)

    # ── Node: call model (pure — just calls LLM) ──
    async def call_model(state: AgentState) -> dict:
        messages = list(state.get("messages", []))
        sys_msg = SystemMessage(content=state.get("system_prompt", ""))
        full_messages = [sys_msg] + messages

        # Stream tokens through callback (for real-time display)
        accumulated = ""
        full_response = None
        async for chunk in llm_with_tools.astream(full_messages):
            full_response = chunk
            token = getattr(chunk, "content", "")
            if isinstance(token, str) and token:
                accumulated += token
                if on_stream_token:
                    on_stream_token(token)

        if full_response is None:
            return {"should_continue": False}

        # Accumulate tool calls from streaming chunks
        tool_calls = _build_tool_calls(full_response, accumulated, uuid)

        # Track usage via runtime callback
        _track_usage(full_response)

        stop_reason = None
        if hasattr(full_response, "response_metadata") and full_response.response_metadata:
            finish = full_response.response_metadata.get("finish_reason", "")
            stop_reason = "tool_use" if finish == "tool_calls" else ("end_turn" if finish == "stop" else None)

        ai_msg = AIMessage(
            content=accumulated,
            additional_kwargs=getattr(full_response, "additional_kwargs", {}),
            response_metadata=getattr(full_response, "response_metadata", {}),
            id=getattr(full_response, "id", None),
            tool_calls=tool_calls,
        )

        return {
            "messages": [ai_msg],
            "last_stop_reason": stop_reason,
        }

    # ── Node: execute tools (pure — just calls tools, no permission/budget/cache) ──
    async def execute_tools(state: AgentState) -> dict:
        messages = list(state.get("messages", []))
        if not messages:
            return {"should_continue": False}

        last_msg = messages[-1]
        if not isinstance(last_msg, AIMessage):
            return {"should_continue": False}

        tool_calls = list(getattr(last_msg, "tool_calls", []) or [])
        if not tool_calls:
            return {"should_continue": False}

        tool_messages = []
        for tc in tool_calls:
            tool_name = tc.get("name", "")
            tool_args = tc.get("args", {})
            tool_call_id = tc.get("id", str(uuid.uuid4()))

            # Notify tool start
            native_tool = _find_native_tool(tools, tool_name)
            call_display = native_tool.format_call(tool_args) if native_tool else tool_name
            activity = native_tool.get_activity_description(tool_args) if native_tool else tool_name
            if on_tool_start:
                on_tool_start(tool_name, activity)

            # Execute tool (permission/cache/budget handled by middleware)
            if native_tool:
                try:
                    ctx = {"file_cache": file_cache, "_parent_engine": None}
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

            # Result budget (applied here for simplicity; could move to middleware)
            max_chars = getattr(native_tool, "max_result_chars", 50_000) if native_tool else 50_000
            if max_chars != float("inf") and len(content) > max_chars and result_temp_dir:
                os.makedirs(result_temp_dir, exist_ok=True)
                rf = os.path.join(result_temp_dir, f"result_{tool_call_id[:12]}.txt")
                try:
                    with open(rf, "w", encoding="utf-8") as f:
                        f.write(content)
                    content = f"[Tool result too large ({len(content):,} chars). Full content saved to {rf}. Preview:\n{content[:500]}...\nUse Read to access the full result."
                except Exception:
                    content = content[:max_chars] + f"\n...[truncated at {max_chars} chars]"

            if on_tool_end:
                on_tool_end(tool_name, content[:200])

            tool_messages.append(ToolMessage(
                content=str(content), tool_call_id=tool_call_id, name=tool_name,
            ))

        turn_count = state.get("turn_count", 0) + 1
        max_t = state.get("max_turns")
        return {
            "messages": tool_messages,
            "turn_count": turn_count,
            "should_continue": not (max_t and turn_count > max_t),
        }

    # ── Router ──
    def router(state: AgentState) -> str:
        if state.get("abort_signal"):
            return "end"
        if not state.get("should_continue", True):
            return "end"
        msgs = state.get("messages", [])
        if not msgs:
            return "end"
        last = msgs[-1]
        if isinstance(last, AIMessage):
            tc = getattr(last, "tool_calls", None)
            if tc and tc:
                max_t = state.get("max_turns")
                if max_t and state.get("turn_count", 0) >= max_t:
                    return "end"
                return "tools"
        return "end"

    workflow.add_node("agent", call_model)
    workflow.add_node("tools", execute_tools)
    workflow.set_entry_point("agent")
    workflow.add_conditional_edges("agent", router, {"tools": "tools", "end": END})
    workflow.add_edge("tools", "agent")

    return workflow.compile(checkpointer=MemorySaver())


# ── Helpers ──

def _find_native_tool(tools: list, name: str):
    for t in tools:
        if t.name == name or name in (t.aliases or []):
            return t
    return None


def _build_tool_calls(full_response, accumulated: str, uuid_mod) -> list:
    """Build tool calls from streaming chunks (handle DeepSeek tool_call_chunks)."""
    tool_calls = list(getattr(full_response, "tool_calls", []) or [])
    if not tool_calls:
        accumulated_tcs: dict[int, dict] = {}
        # Check for tool_call_chunks (DeepSeek streaming format)
        tc_chunks = getattr(full_response, "tool_call_chunks", None) or []
        for tcc in tc_chunks:
            idx = tcc.get("index", 0)
            if idx not in accumulated_tcs:
                accumulated_tcs[idx] = {"name": "", "id": "", "args_str": ""}
            if tcc.get("name"):
                accumulated_tcs[idx]["name"] = tcc["name"]
            if tcc.get("id"):
                accumulated_tcs[idx]["id"] = tcc["id"]
            if tcc.get("args"):
                accumulated_tcs[idx]["args_str"] += tcc["args"]
        for idx in sorted(accumulated_tcs.keys()):
            tc = accumulated_tcs[idx]
            if tc["name"]:
                try:
                    args = json.loads(tc["args_str"]) if tc["args_str"] else {}
                except json.JSONDecodeError:
                    args = {}
                tool_calls.append({
                    "name": tc["name"], "args": args,
                    "id": tc["id"] or str(uuid_mod.uuid4()), "type": "tool_call",
                })
    return tool_calls


def _track_usage(response):
    """Best-effort token usage tracking."""
    pass  # Handled by TokenTrackingMiddleware
