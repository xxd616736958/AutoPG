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
):
    """Build agent StateGraph with ToolNode + tools_condition."""
    llm = _build_llm(provider, model, api_key, base_url)
    # Convert native tools to LangChain StructuredTools
    llm_with_tools = llm.bind_tools(tools)

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

    tool_node = ToolNode(tools, handle_tool_errors=True)

    workflow.add_node("agent", call_model)
    workflow.add_node("tools", tool_node)
    workflow.set_entry_point("agent")
    workflow.add_conditional_edges("agent", tools_condition, {"tools": "tools", END: END})
    workflow.add_edge("tools", "agent")

    return workflow.compile(checkpointer=checkpointer or MemorySaver())


compiled_graph = None  # Built lazily
