"""
Central agent graph — build_agent_graph() is the ONLY agent factory.
Used by: main agent, Explore, Plan, general-purpose subagents.
Module-level compiled_graph for langgraph serve.
"""
import os, json, uuid
from typing import Optional, Callable
from langchain_core.messages import AIMessage, ToolMessage, SystemMessage, HumanMessage
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
try:
    from langgraph.checkpoint.sqlite import SqliteSaver
except ImportError:
    SqliteSaver = None

from .agent.state import AgentState, create_initial_state
from .context_schema import AgentContext


def _build_llm(provider: str, model: str, api_key: str = None, base_url: str = None):
    if provider == "deepseek":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model,
            api_key=api_key or os.environ.get("DEEPSEEK_API_KEY"),
            base_url=base_url or "https://api.deepseek.com/v1",
            temperature=0.7, max_tokens=8192, streaming=True,
        )
    else:
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            model=model,
            api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"),
            max_tokens=8192, temperature=1.0, streaming=True,
        )


def _find_tool(tools: list, name: str):
    for t in tools:
        if t.name == name or name in (t.aliases or []):
            return t
    return None


def _wrap_node(node_fn, stack, before=None, after=None, wrap=None):
    """Compile-time middleware weaving. Fuses middleware hooks into graph node."""
    async def wrapped(state, config, *, context=None, **kwargs):
        ctx = context
        if ctx is None:
            return await node_fn(state, config, **kwargs)

        if before:
            delta = await getattr(stack, f"run_{before}")(state, ctx)
            if delta: state = {**state, **delta}

        if wrap:
            result = await getattr(stack, f"run_{wrap}")(state, ctx,
                lambda s: node_fn(s, config, context=ctx, **kwargs))
        else:
            result = await node_fn(state, config, context=ctx, **kwargs)

        if after:
            delta = await getattr(stack, f"run_{after}")(state, ctx)
            if delta: result = {**result, **delta}

        return result
    return wrapped


def build_agent_graph(
    tools: list,
    model: str,
    middleware_stack,
    *,
    provider: str = "deepseek",
    api_key: str = None,
    base_url: str = None,
    system_prompt: str = "",
    max_turns: int = 100,
    checkpointer=None,
) -> 'CompiledStateGraph':
    """
    Build a compiled agent StateGraph. THE ONLY agent factory in the project.

    Main agent and all subagents use this same function.
    Compile-time middleware weaving fuses hooks into nodes.
    """
    llm = _build_llm(provider, model, api_key, base_url)
    lc_tools = [t.get_langchain_tool() for t in tools if t.is_enabled()]
    tool_map = {t.name: t for t in lc_tools}
    llm_with_tools = llm.bind_tools(lc_tools)

    workflow = StateGraph(AgentState)

    # ═══════════════════════════════════════════════════════════
    # Pure business nodes — no cross-cutting logic
    # ═══════════════════════════════════════════════════════════

    async def call_model(state, config, *, context: AgentContext = None):
        ctx = context or config.get("configurable", {}).get("_context")
        if ctx is None:
            from ..context_schema import AgentContext as AC
            ctx = AC()
        messages = list(state.get("messages", []))
        sys_msg = SystemMessage(content=state.get("system_prompt", system_prompt))

        accumulated = ""
        full_response = None
        accumulated_tcs: dict[int, dict] = {}

        async for chunk in llm_with_tools.astream([sys_msg] + messages):
            full_response = chunk
            token = getattr(chunk, "content", "")
            if isinstance(token, str) and token:
                accumulated += token
                if ctx.on_stream_token:
                    ctx.on_stream_token(token)

            for tcc in (getattr(chunk, "tool_call_chunks", None) or []):
                idx = tcc.get("index", 0)
                if idx not in accumulated_tcs:
                    accumulated_tcs[idx] = {"name": "", "id": "", "args_str": ""}
                if tcc.get("name"): accumulated_tcs[idx]["name"] = tcc["name"]
                if tcc.get("id"): accumulated_tcs[idx]["id"] = tcc["id"]
                if tcc.get("args"): accumulated_tcs[idx]["args_str"] += tcc["args"]

        if full_response is None:
            return {"should_continue": False}

        # Build tool calls from accumulated chunks
        tool_calls = []
        for idx in sorted(accumulated_tcs.keys()):
            tc = accumulated_tcs[idx]
            if tc["name"]:
                try:
                    args = json.loads(tc["args_str"]) if tc["args_str"] else {}
                except json.JSONDecodeError:
                    args = {}
                tool_calls.append({
                    "name": tc["name"], "args": args,
                    "id": tc["id"] or str(uuid.uuid4()), "type": "tool_call",
                })
        if not tool_calls:
            tool_calls = list(getattr(full_response, "tool_calls", []) or [])

        # Track usage
        if hasattr(full_response, "usage_metadata") and full_response.usage_metadata:
            um = full_response.usage_metadata
            ctx.total_usage["input_tokens"] += um.get("input_tokens", 0)
            ctx.total_usage["output_tokens"] += um.get("output_tokens", 0)

        return {
            "messages": [
                AIMessage(content=accumulated, tool_calls=tool_calls,
                          id=getattr(full_response, "id", None))
            ],
            "last_stop_reason": "tool_use" if tool_calls else "end_turn",
        }

    async def execute_tools(state, config, *, context: AgentContext = None):
        ctx = context or config.get("configurable", {}).get("_context")
        if ctx is None:
            from ..context_schema import AgentContext as AC
            ctx = AC()
        messages = list(state.get("messages", []))
        if not messages: return {"should_continue": False}

        last_msg = messages[-1]
        if not isinstance(last_msg, AIMessage): return {"should_continue": False}

        tool_calls = list(getattr(last_msg, "tool_calls", []) or [])
        if not tool_calls: return {"should_continue": False}

        tool_messages = []
        for tc in tool_calls:
            tool = _find_tool(tools, tc["name"])
            if not tool:
                tool_messages.append(ToolMessage(
                    content=f"Tool '{tc['name']}' not found",
                    tool_call_id=tc.get("id", ""), name=tc["name"],
                ))
                continue

            tc_id = tc.get("id", str(uuid.uuid4()))
            if ctx.on_tool_start:
                ctx.on_tool_start(tc["name"], tool.format_call(tc.get("args", {})))

            try:
                result = await tool.call(tc.get("args", {}), {
                    "cwd": ctx.cwd,
                    "file_cache": ctx.file_cache,
                    "tool_call_id": tc_id,
                    "_parent_engine": ctx._parent_engine,
                })
                result_data = result.get("data", result) if isinstance(result, dict) else result
                content = json.dumps(result_data, ensure_ascii=False, indent=2) if not isinstance(result_data, str) else result_data
            except Exception as e:
                content = f"Error: {str(e)}"

            # Tool result budget
            max_chars = getattr(tool, "max_result_chars", 50_000)
            if max_chars != float("inf") and len(content) > max_chars and ctx.result_temp_dir:
                os.makedirs(ctx.result_temp_dir, exist_ok=True)
                rf = os.path.join(ctx.result_temp_dir, f"result_{tc_id[:12]}.txt")
                try:
                    with open(rf, "w", encoding="utf-8") as f:
                        f.write(content)
                    content = (f"[Tool result too large ({len(content):,} chars). "
                               f"Full content saved to {rf}. Preview:\n{content[:500]}...")
                except Exception:
                    content = content[:max_chars] + f"\n...[truncated]"

            if ctx.on_tool_end:
                preview = content[:200]
                try:
                    fmt = json.loads(content) if content.startswith("{") else content
                except Exception:
                    fmt = content
                formatted = tool.format_result(fmt)
                ctx.on_tool_end(tc["name"], formatted)

            tool_messages.append(ToolMessage(
                content=str(content), tool_call_id=tc_id, name=tc["name"],
            ))

        turn = state.get("turn_count", 0) + 1
        return {
            "messages": tool_messages,
            "turn_count": turn,
            "should_continue": turn < state.get("max_turns", max_turns),
        }

    def router(state) -> str:
        if not state.get("should_continue", True): return "end"
        msgs = state.get("messages", [])
        if not msgs: return "end"
        last = msgs[-1]
        if isinstance(last, AIMessage) and (getattr(last, "tool_calls", None) or []):
            return "tools"
        return "end"

    # ═══════════════════════════════════════════════════════════
    # Compile-time middleware weaving
    # ═══════════════════════════════════════════════════════════

    wrapped_agent = _wrap_node(call_model, middleware_stack,
        before="abefore_model", after="aafter_model")
    wrapped_tools = _wrap_node(execute_tools, middleware_stack,
        wrap="awrap_tool_call")

    workflow.add_node("agent", wrapped_agent)
    workflow.add_node("tools", wrapped_tools)
    workflow.set_entry_point("agent")
    workflow.add_conditional_edges("agent", router, {"tools": "tools", "end": END})
    workflow.add_edge("tools", "agent")

    return workflow.compile(checkpointer=checkpointer or MemorySaver())


# ═══════════════════════════════════════════════════════════════
# Module-level export — langgraph serve entry point
# ═══════════════════════════════════════════════════════════════

def _get_db_path() -> str:
    d = os.path.join(os.path.expanduser("~/.db-claude"), "checkpoints")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "sessions.db")


compiled_graph = None  # Built lazily by QueryEngine with actual tools/middleware
