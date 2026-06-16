"""
Subagent execution — matching Claude Code's runAgent.ts + createSubagentContext.
"""
import uuid, asyncio
from typing import Optional, Callable
from dataclasses import dataclass, field
from langchain_core.messages import HumanMessage, AIMessage

from .tools.agent_definitions import AgentDefinition, find_agent_definition


# ── Background task registry (Claude Code: LocalAgentTask) ──

@dataclass
class BackgroundAgentState:
    agent_id: str
    description: str
    agent_type: str
    status: str = "running"  # running | completed | failed
    result: Optional[dict] = None
    task: Optional[asyncio.Task] = None

_background_agents: dict[str, BackgroundAgentState] = {}


def get_background_agent(agent_id: str) -> Optional[BackgroundAgentState]:
    return _background_agents.get(agent_id)


def list_background_agents() -> list[BackgroundAgentState]:
    return list(_background_agents.values())


def _cleanup_completed():
    """Remove completed agents that have been fetched."""
    to_remove = [aid for aid, a in _background_agents.items()
                 if a.status in ("completed", "failed")]
    for aid in to_remove:
        del _background_agents[aid]


# ── Context creation (Claude Code: createSubagentContext) ──

def create_subagent_context(
    parent_engine: 'QueryEngine',
    agent_def: AgentDefinition,
    agent_id: str,
    prompt: str,
) -> dict:
    """
    Build subagent QueryEngine kwargs with full state isolation.
    Claude Code: createSubagentContext() in forkedAgent.ts.

    Isolation guarantees:
    - File cache: copied from parent (shared reads, no writes back)
    - Permission: auto-deny (subagent cannot prompt user)
    - Tools: filtered per agent_def
    - Callbacks: muted (no stream/callback pollution to parent)
    - Abort: child controller linked to parent
    """
    from ..tools import create_default_tools

    all_tools = list(parent_engine.tools) if parent_engine.tools else create_default_tools().list_enabled()

    # Filter tools per agent definition
    if agent_def.tools == ["*"]:
        subagent_tools = [t for t in all_tools if t.name not in agent_def.disallowed_tools]
    else:
        allowed = set(agent_def.tools)
        subagent_tools = [t for t in all_tools if t.name in allowed]

    # Resolve model
    model = parent_engine.model_name if agent_def.model == "inherit" else agent_def.model

    return dict(
        tools=subagent_tools,
        model_name=model,
        provider=parent_engine.provider,
        api_key=parent_engine.api_key,
        base_url=parent_engine.base_url,
        cwd=parent_engine.cwd,
        max_turns=agent_def.max_turns,
        permission_mode=agent_def.permission_mode,
        is_non_interactive_session=True,
        # ── Isolation ──
        custom_system_prompt=agent_def.system_prompt if agent_def.system_prompt else None,
        # Subagent cannot prompt user — auto-deny all
        on_permission_check=lambda *a: False,
        # No stream callbacks to parent
        on_stream_token=None,
        on_tool_start=None,
        on_tool_end=None,
        # Inherit file cache for shared reads
        initial_messages=[HumanMessage(content=prompt)],
    )


# ── Execution (Claude Code: runAgent) ──

async def run_subagent_inline(
    parent_engine: 'QueryEngine',
    agent_def: AgentDefinition,
    prompt: str,
) -> dict:
    """
    Run a subagent synchronously, return summarized result.
    Claude Code: runAgent() yielding to parent conversation.
    """
    agent_id = str(uuid.uuid4())
    config = create_subagent_context(parent_engine, agent_def, agent_id, prompt)

    from ..agent.query_engine import QueryEngine
    sub = QueryEngine(**config)
    sub.set_session_id(agent_id)

    # Link abort: parent abort → child abort
    parent_engine._child_engines.append(sub)

    try:
        accumulated_text = ""
        messages_count = 0
        async for event in sub.submit_message(prompt):
            if event.get("type") == "token":
                accumulated_text += event.get("content", "")
            elif event.get("type") == "tool_start":
                messages_count += 1
            elif event.get("type") == "result":
                accumulated_text = event.get("result", accumulated_text)
                messages_count += event.get("num_turns", 0)
                break

        return {
            "status": "completed",
            "agent_type": agent_def.agent_type,
            "result": accumulated_text[:3000],  # Summarized — full context stays in subagent
            "message_count": messages_count,
        }
    except Exception as e:
        return {"status": "failed", "error": str(e)}
    finally:
        sub.cleanup()
        if sub in parent_engine._child_engines:
            parent_engine._child_engines.remove(sub)


async def run_subagent_background(
    parent_engine: 'QueryEngine',
    agent_def: AgentDefinition,
    description: str,
    prompt: str,
) -> dict:
    """
    Run subagent in background, return immediately with agent_id.
    Claude Code: runAsyncAgentLifecycle() / LocalAgentTask.
    """
    agent_id = str(uuid.uuid4())
    config = create_subagent_context(parent_engine, agent_def, agent_id, prompt)

    state = BackgroundAgentState(
        agent_id=agent_id,
        description=description,
        agent_type=agent_def.agent_type,
    )
    _background_agents[agent_id] = state

    async def _run():
        from ..agent.query_engine import QueryEngine
        sub = QueryEngine(**config)
        sub.set_session_id(agent_id)
        parent_engine._child_engines.append(sub)

        try:
            final = None
            async for event in sub.submit_message(prompt):
                if event.get("type") == "result":
                    final = event
                    break
            state.status = "completed"
            state.result = final
        except Exception as e:
            state.status = "failed"
            state.result = {"error": str(e)}
        finally:
            sub.cleanup()
            if sub in parent_engine._child_engines:
                parent_engine._child_engines.remove(sub)

    state.task = asyncio.create_task(_run())

    return {
        "status": "started",
        "agent_id": agent_id,
        "agent_type": agent_def.agent_type,
        "description": description,
    }
