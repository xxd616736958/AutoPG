"""
Central agent graph — LangGraph ToolNode + tools_condition + Runtime.
Module-level compiled_graph for langgraph serve.
"""
import os, json, uuid
from typing import Optional, Callable
from langchain_core.messages import AIMessage, SystemMessage
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.checkpoint.memory import MemorySaver

from .agent.state import AgentState
from .context_schema import AgentContext
from .utils.hooks import execute_matching_hooks


def _build_llm(provider: str, model: str, api_key: str = None, base_url: str = None):
    if provider == "deepseek":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model, api_key=api_key or os.environ.get("DEEPSEEK_API_KEY"),
            base_url=base_url or "https://api.deepseek.com/v1",
            temperature=0.7, max_tokens=8192, streaming=True,
        )
    else:
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            model=model, api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"),
            max_tokens=8192, temperature=1.0, streaming=True,
        )


def build_agent_graph(
    tools: list,
    model: str,
    middleware_stack,
    *,
    provider: str = "deepseek",
    api_key: str = None, base_url: str = None,
    system_prompt: str = "",
    max_turns: int = 100,
    checkpointer=None,
    hooks_config_param: dict = None,
):
    """Build agent StateGraph with ToolNode + tools_condition."""
    llm = _build_llm(provider, model, api_key, base_url)
    llm_with_tools = llm.bind_tools(tools)

    # ── User hooks: PreToolUse / PostToolUse via ToolNode awrap_tool_call ──
    # Clean separation: ONLY execution control (block/allow). Display is handled by query_engine.
    hooks_config = hooks_config_param if hooks_config_param else {}

    async def _tool_hook_wrapper(request, execute):
        try:
            tool_name = request.tool_call.get("name", "")
        except Exception:
            return await execute(request)
        tool_args = request.tool_call.get("args", {})
        if hooks_config.get("PreToolUse"):
            block = await execute_matching_hooks("PreToolUse", tool_name, tool_args, hooks_config)
            if block and "Blocked" in str(block):
                from langchain_core.messages import ToolMessage
                return ToolMessage(content=f"Hook blocked: {block}", tool_call_id=request.tool_call.get("id",""), name=tool_name)
        result = await execute(request)
        if hooks_config.get("PostToolUse"):
            hook_msg = await execute_matching_hooks("PostToolUse", tool_name, tool_args, hooks_config)
            if hook_msg:
                tc_id = request.tool_call.get("id", str(uuid.uuid4()))
                _hook_outputs[tc_id] = hook_msg
                # Also write to stdout for immediate visibility
                import sys
                for line in hook_msg.strip().split("\n")[:5]:
                    sys.stdout.write(f"\n  ⎿  {line[:120]}")
                sys.stdout.write("\n")
                sys.stdout.flush()
        return result

    workflow = StateGraph(AgentState)

    # ═══════════════════════════════════════════════════
    # Agent node — call LLM, stream tokens
    # ═══════════════════════════════════════════════════

    async def call_model(state, config, *, runtime=None):
        ctx = runtime.context if runtime and hasattr(runtime, 'context') else None
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
                if ctx and ctx.on_stream_token:
                    ctx.on_stream_token(token)
            for tcc in (getattr(chunk, "tool_call_chunks", None) or []):
                idx = tcc.get("index", 0)
                if idx not in accumulated_tcs:
                    accumulated_tcs[idx] = {"name": "", "id": "", "args_str": ""}
                if tcc.get("name"): accumulated_tcs[idx]["name"] = tcc["name"]
                if tcc.get("id"): accumulated_tcs[idx]["id"] = tcc["id"]
                if tcc.get("args"): accumulated_tcs[idx]["args_str"] += tcc["args"]

        if full_response is None:
            return {"should_continue": False, "messages": []}

        # Build tool calls
        tool_calls = []
        for idx in sorted(accumulated_tcs.keys()):
            tc = accumulated_tcs[idx]
            if tc["name"]:
                try: args = json.loads(tc["args_str"]) if tc["args_str"] else {}
                except json.JSONDecodeError: args = {}
                tool_calls.append({"name": tc["name"], "args": args,
                                   "id": tc["id"] or str(uuid.uuid4()), "type": "tool_call"})
        if not tool_calls:
            tool_calls = list(getattr(full_response, "tool_calls", []) or [])

        return {
            "messages": [AIMessage(content=accumulated, tool_calls=tool_calls,
                                   id=getattr(full_response, "id", None))],
            "last_stop_reason": "tool_use" if tool_calls else "end_turn",
        }

    # ═══════════════════════════════════════════════════
    # ToolNode — LangGraph built-in tool execution
    # ═══════════════════════════════════════════════════

    tool_node = ToolNode(tools, handle_tool_errors=True,
                        awrap_tool_call=_tool_hook_wrapper if hooks_config else None)

    workflow.add_node("agent", call_model)
    workflow.add_node("tools", tool_node)
    workflow.set_entry_point("agent")
    workflow.add_conditional_edges("agent", tools_condition, {"tools": "tools", END: END})
    workflow.add_edge("tools", "agent")

    return workflow.compile(checkpointer=checkpointer or MemorySaver())


compiled_graph = None  # Built lazily


def create_checkpointer(backend: str = "sqlite", **kwargs):
    """Factory: create checkpointer from config. Default: SQLite."""
    if backend == "sqlite":
        import os
        db_path = kwargs.get("db_path") or os.path.join(
            os.path.expanduser("~/.db-claude"), "checkpoints", "sessions.db"
        )
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        try:
            from langgraph.checkpoint.sqlite import SqliteSaver
            return SqliteSaver.from_conn_string(db_path)
        except ImportError:
            return MemorySaver()
    elif backend == "memory":
        return MemorySaver()
    else:
        return MemorySaver()


def load_checkpointer_from_config(config: dict = None):
    """Read checkpoint config from config dict."""
    import os, json
    if config is None:
        try:
            with open(os.path.join(os.path.expanduser("~/.db-claude"), "config.json")) as f:
                config = json.load(f)
        except Exception:
            config = {}
    cp = config.get("checkpoint", {})
    backend = cp.get("backend", "sqlite")
    kwargs = cp.get(backend, {})
    return create_checkpointer(backend, **kwargs)

# Side channel: hook output indexed by tool_call_id (ToolNode rebuilds ToolMessage, discarding custom attrs)
_hook_outputs: dict[str, str] = {}

def pop_hook_output(tool_call_id: str) -> str:
    """Retrieve and clear hook output for a tool call. Called by query_engine."""
    return _hook_outputs.pop(tool_call_id, "")

def drain_hook_outputs() -> str:
    """Drain all pending hook outputs. Returns concatenated string."""
    result = "\n".join(v for v in _hook_outputs.values() if v)
    _hook_outputs.clear()
    return result
