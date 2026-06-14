"""
Core agent query loop for db-claude.
This is the LangGraph implementation of Claude Code's query.ts loop.
Architecturally identical to the query() function and QueryEngine.submitMessage().

Supports multiple LLM providers: Anthropic (default) and DeepSeek.
"""
import json
import os
import uuid
from typing import AsyncGenerator, Optional, Any
from datetime import datetime

from langchain_core.messages import (
    BaseMessage,
    HumanMessage,
    AIMessage,
    ToolMessage,
    SystemMessage,
)
from langchain_core.tools import BaseTool as LangChainBaseTool
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from .state import AgentState, create_initial_state
from .system_prompt import build_system_prompt, get_user_context, get_system_context


class QueryEngine:
    """
    QueryEngine owns the query lifecycle and session state for a conversation.
    Mirrors Claude Code's QueryEngine class (src/QueryEngine.ts).

    Supports providers:
    - "anthropic": Claude models via ChatAnthropic
    - "deepseek": DeepSeek models via ChatOpenAI (OpenAI-compatible)
    """

    def __init__(
        self,
        tools: list,
        model_name: str = "claude-sonnet-4-6",
        fallback_model: Optional[str] = None,
        cwd: str = "",
        max_turns: Optional[int] = None,
        max_budget_usd: Optional[float] = None,
        permission_mode: str = "default",
        custom_system_prompt: Optional[str] = None,
        append_system_prompt: Optional[str] = None,
        is_non_interactive_session: bool = False,
        initial_messages: Optional[list] = None,
        provider: str = "anthropic",
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        self.tools = tools
        self.model_name = model_name
        self.fallback_model = fallback_model
        self.cwd = cwd
        self.max_turns = max_turns
        self.max_budget_usd = max_budget_usd
        self.permission_mode = permission_mode
        self.custom_system_prompt = custom_system_prompt
        self.append_system_prompt = append_system_prompt
        self.is_non_interactive_session = is_non_interactive_session
        self.provider = provider
        self.api_key = api_key
        self.base_url = base_url

        # Mutable state
        self.mutable_messages: list = initial_messages or []
        self.permission_denials: list = []
        self.total_usage = {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_creation_tokens": 0,
        }
        self.discovered_skill_names: set = set()
        self.loaded_nested_memory_paths: set = set()
        self._abort = False
        self._session_id = str(uuid.uuid4())

    def interrupt(self):
        """Interrupt the current query, mirroring QueryEngine.interrupt()."""
        self._abort = True

    @property
    def session_id(self) -> str:
        return self._session_id

    async def _get_or_build_system_prompt(self) -> str:
        """Build (or retrieve cached) system prompt for the current configuration."""
        parts = await build_system_prompt(
            tools=self.tools,
            model=self.model_name,
            cwd=self.cwd,
            custom_system_prompt=self.custom_system_prompt,
            append_system_prompt=self.append_system_prompt,
        )
        clean_parts = [p for p in parts if p]
        return "\n\n".join(clean_parts)

    async def submit_message(
        self,
        prompt: str,
        options: Optional[dict] = None,
    ) -> dict:
        """
        Submit a user message and run the query loop.
        Mirrors QueryEngine.submitMessage().
        """
        options = options or {}
        start_time = datetime.now()

        # Build system prompt
        system_prompt_text = await self._get_or_build_system_prompt()

        # Get user and system context
        user_context = await get_user_context()
        system_context = await get_system_context()

        # Add user message to mutable state
        user_msg = HumanMessage(content=prompt)
        self.mutable_messages.append(user_msg)

        # Create initial state for this turn
        state = create_initial_state(
            messages=list(self.mutable_messages),
            system_prompt=system_prompt_text,
            user_context=user_context,
            system_context=system_context,
            tools=self._tools_to_langchain(),
            model=self.model_name,
            fallback_model=self.fallback_model,
            max_turns=self.max_turns,
            max_budget_usd=self.max_budget_usd,
            cwd=self.cwd,
            permission_mode=self.permission_mode,
            is_non_interactive_session=self.is_non_interactive_session,
        )

        # Run the agent loop
        try:
            result_state = await self._run_agent_loop(state)

            # Extract result
            new_messages = result_state.get("messages", [])
            self.mutable_messages = list(new_messages)

            # Find the last assistant message for text result
            text_result = ""
            for msg in reversed(self.mutable_messages):
                if isinstance(msg, AIMessage) and msg.content:
                    text_result = str(msg.content)
                    break

            duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)

            return {
                "type": "result",
                "subtype": "success",
                "is_error": False,
                "duration_ms": duration_ms,
                "num_turns": result_state.get("turn_count", 0),
                "result": text_result,
                "stop_reason": result_state.get("last_stop_reason"),
                "session_id": self._session_id,
                "total_cost_usd": 0.0,
                "usage": self.total_usage,
                "permission_denials": self.permission_denials,
            }
        except Exception as e:
            duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
            return {
                "type": "result",
                "subtype": "error_during_execution",
                "is_error": True,
                "duration_ms": duration_ms,
                "num_turns": state.get("turn_count", 0),
                "result": "",
                "stop_reason": None,
                "session_id": self._session_id,
                "total_cost_usd": 0.0,
                "usage": self.total_usage,
                "permission_denials": self.permission_denials,
                "errors": [str(e)],
            }

    def _tools_to_langchain(self) -> list:
        """Convert db-claude tools to LangChain-compatible tools."""
        lc_tools = []
        for tool in self.tools:
            if tool.is_enabled():
                lc_tools.append(tool.get_langchain_tool())
        return lc_tools

    def _build_llm(self):
        """Build the LLM based on the configured provider."""
        if self.provider == "deepseek":
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(
                model=self.model_name,
                api_key=self.api_key or os.environ.get("DEEPSEEK_API_KEY"),
                base_url=self.base_url or "https://api.deepseek.com/v1",
                temperature=0.7,
                max_tokens=8192,
                streaming=True,
            )
        else:
            # Default: Anthropic
            from langchain_anthropic import ChatAnthropic
            return ChatAnthropic(
                model=self.model_name,
                api_key=self.api_key or os.environ.get("ANTHROPIC_API_KEY"),
                base_url=self.base_url or os.environ.get("ANTHROPIC_BASE_URL"),
                max_tokens=8192,
                temperature=1.0,
                streaming=True,
            )

    async def _run_agent_loop(self, initial_state: AgentState) -> dict:
        """
        Run the main agent loop using LangGraph.
        Mirrors the query.ts while(true) loop structure.
        """
        # Build the LLM
        llm = self._build_llm()

        # Build tool map
        lc_tools = self._tools_to_langchain()
        tool_map = {t.name: t for t in lc_tools}

        # Bind tools to LLM
        llm_with_tools = llm.bind_tools(lc_tools)

        # Build the graph
        workflow = StateGraph(AgentState)

        # Node: call the model
        async def call_model(state: AgentState) -> dict:
            """Call the model with current messages and tools."""
            if state.get("abort_signal"):
                return {"should_continue": False}

            messages = list(state.get("messages", []))

            # Prepend system prompt as SystemMessage
            system_prompt = state.get("system_prompt", "")
            sys_msg = SystemMessage(content=system_prompt)

            # Build the full message list
            full_messages = [sys_msg] + messages

            # Call model
            response = await llm_with_tools.ainvoke(full_messages)

            # Track usage from response
            usage = state.get("total_usage", {})
            if hasattr(response, "usage_metadata") and response.usage_metadata:
                um = response.usage_metadata
                usage["input_tokens"] = usage.get("input_tokens", 0) + um.get("input_tokens", 0)
                usage["output_tokens"] = usage.get("output_tokens", 0) + um.get("output_tokens", 0)
            elif hasattr(response, "response_metadata") and response.response_metadata:
                rm = response.response_metadata
                tu = rm.get("token_usage", {})
                usage["input_tokens"] = usage.get("input_tokens", 0) + tu.get("prompt_tokens", 0)
                usage["output_tokens"] = usage.get("output_tokens", 0) + tu.get("completion_tokens", 0)

            # Accumulate usage
            self.total_usage["input_tokens"] += usage.get("input_tokens", 0)
            self.total_usage["output_tokens"] += usage.get("output_tokens", 0)

            # Determine stop_reason
            stop_reason = None
            if response.response_metadata:
                finish = response.response_metadata.get("finish_reason", "")
                if finish == "tool_calls":
                    stop_reason = "tool_use"
                elif finish == "stop":
                    stop_reason = "end_turn"

            return {
                "messages": [response],
                "total_usage": usage,
                "last_stop_reason": stop_reason,
            }

        # Node: execute tools
        async def execute_tools(state: AgentState) -> dict:
            """Execute tool calls from the last AI message."""
            messages = list(state.get("messages", []))
            if not messages:
                return {"should_continue": False}

            last_msg = messages[-1]
            if not isinstance(last_msg, AIMessage):
                return {"should_continue": False}

            # Extract tool calls — handle both LangChain format and raw format
            tool_calls = []
            if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
                tool_calls = last_msg.tool_calls
            elif "tool_calls" in (last_msg.additional_kwargs or {}):
                tool_calls = last_msg.additional_kwargs["tool_calls"]

            if not tool_calls:
                return {"should_continue": False}

            # Execute each tool call
            tool_messages = []
            for tc in tool_calls:
                tool_name = tc.get("name", "")
                tool_args = tc.get("args", {})
                tool_call_id = tc.get("id", str(uuid.uuid4()))

                # Find the tool in our native registry
                native_tool = None
                for t in self.tools:
                    if t.name == tool_name or tool_name in (t.aliases or []):
                        native_tool = t
                        break

                if native_tool:
                    try:
                        context = state.get("tool_use_context", {})
                        result = await native_tool.call(tool_args, context)
                        if isinstance(result, dict):
                            result_data = result.get("data", result)
                        else:
                            result_data = result
                        content = json.dumps(result_data, ensure_ascii=False, indent=2) if not isinstance(result_data, str) else result_data
                    except Exception as e:
                        content = f"Error: {str(e)}"
                else:
                    # Try LangChain tool
                    lc_tool = tool_map.get(tool_name)
                    if lc_tool:
                        try:
                            result = await lc_tool.ainvoke(tool_args)
                            content = json.dumps(result, ensure_ascii=False, indent=2) if not isinstance(result, str) else result
                        except Exception as e:
                            content = f"Error: {str(e)}"
                    else:
                        content = f"Tool '{tool_name}' not found"

                tool_msg = ToolMessage(
                    content=str(content),
                    tool_call_id=tool_call_id,
                    name=tool_name,
                )
                tool_messages.append(tool_msg)

            # Increment turn count
            turn_count = state.get("turn_count", 0) + 1

            # Check max turns
            max_turns = state.get("max_turns")
            if max_turns and turn_count > max_turns:
                return {
                    "messages": tool_messages,
                    "turn_count": turn_count,
                    "should_continue": False,
                    "terminal_reason": "max_turns",
                }

            return {
                "messages": tool_messages,
                "turn_count": turn_count,
                "should_continue": True,
            }

        # Router: determine next step
        def should_continue(state: AgentState) -> str:
            """Route to tools or end."""
            if state.get("abort_signal"):
                return "end"
            if not state.get("should_continue", True):
                return "end"

            messages = state.get("messages", [])
            if not messages:
                return "end"

            last_msg = messages[-1]
            if isinstance(last_msg, AIMessage):
                # Check for tool calls
                has_tool_calls = False
                if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
                    has_tool_calls = len(last_msg.tool_calls) > 0
                elif "tool_calls" in (last_msg.additional_kwargs or {}):
                    has_tool_calls = len(last_msg.additional_kwargs["tool_calls"]) > 0

                if has_tool_calls:
                    max_turns = state.get("max_turns")
                    turn_count = state.get("turn_count", 0)
                    if max_turns and turn_count >= max_turns:
                        return "end"
                    return "tools"

            return "end"

        # Add nodes
        workflow.add_node("agent", call_model)
        workflow.add_node("tools", execute_tools)

        # Add edges
        workflow.set_entry_point("agent")
        workflow.add_conditional_edges(
            "agent",
            should_continue,
            {
                "tools": "tools",
                "end": END,
            },
        )
        workflow.add_edge("tools", "agent")  # Loop back to agent after tools

        # Compile with memory checkpointer
        checkpointer = MemorySaver()
        app = workflow.compile(checkpointer=checkpointer)

        # Run the graph
        config = {"configurable": {"thread_id": self._session_id}}

        initial_messages = list(initial_state.get("messages", []))

        final_state = None
        async for event in app.astream(
            {"messages": initial_messages},
            config=config,
            stream_mode="values",
        ):
            final_state = event
            if self._abort:
                break

        if final_state is None:
            return initial_state

        result = dict(initial_state)
        if isinstance(final_state, dict):
            result.update(final_state)
        return result
