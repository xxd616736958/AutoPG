"""
Subagent execution — matching AutoPG's runAgent.ts + createSubagentContext.
"""
import uuid, asyncio, time
from typing import Optional
from dataclasses import dataclass, field

from .tools.agent_definitions import AgentDefinition


@dataclass
class BackgroundAgentState:
    agent_id: str
    description: str
    agent_type: str
    prompt: str = ""
    status: str = "running"  # running | completed | failed | cancelled
    result: Optional[dict] = None
    error: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    task: Optional[asyncio.Task] = None

    def to_dict(self, include_result: bool = True) -> dict:
        data = {
            "agent_id": self.agent_id,
            "description": self.description,
            "agent_type": self.agent_type,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if self.error:
            data["error"] = self.error
        if include_result and self.result is not None:
            data["result"] = self.result
        return data


_background_agents: dict[str, BackgroundAgentState] = {}


def get_background_agent(agent_id: str) -> Optional[BackgroundAgentState]:
    return _background_agents.get(agent_id)


def list_background_agents() -> list[BackgroundAgentState]:
    return list(_background_agents.values())


def cancel_background_agent(agent_id: str) -> bool:
    state = _background_agents.get(agent_id)
    if not state:
        return False
    if state.task and not state.task.done():
        state.task.cancel()
    state.status = "cancelled"
    state.updated_at = time.time()
    return True


def _tool_name(tool) -> str:
    return getattr(tool, "name", "")


def create_subagent_context(
    parent_engine: 'QueryEngine',
    agent_def: AgentDefinition,
    agent_id: str,
) -> dict:
    """
    Build isolated QueryEngine kwargs for a forked subagent.

    Isolation guarantees:
    - independent session id and conversation history
    - filtered tools per agent definition
    - non-interactive permissions; child cannot prompt the user
    - muted callbacks so child streaming does not pollute parent output
    - parent interrupt propagates through parent_engine._child_engines
    """
    all_tools = list(parent_engine.tools or [])

    if agent_def.tools == ["*"]:
        disallowed = set(agent_def.disallowed_tools)
        subagent_tools = [t for t in all_tools if _tool_name(t) not in disallowed]
    else:
        allowed = set(agent_def.tools)
        subagent_tools = [t for t in all_tools if _tool_name(t) in allowed]

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
        custom_system_prompt=agent_def.system_prompt if agent_def.system_prompt else None,
        append_system_prompt=(
            "\n\n# Subagent isolation\n"
            "You are a forked subagent. Work independently from the parent agent. "
            "Return a concise final report with evidence, file paths, SQL, or commands used. "
            "Do not ask the user questions; make reasonable assumptions and state them."
        ),
        on_permission_check=lambda *a: False,
        on_stream_token=None,
        on_tool_start=None,
        on_tool_end=None,
        initial_messages=[],
    )


async def run_subagent_inline(
    parent_engine: 'QueryEngine',
    agent_def: AgentDefinition,
    prompt: str,
) -> dict:
    """Run a forked subagent synchronously and return a compact result."""
    agent_id = str(uuid.uuid4())
    config = create_subagent_context(parent_engine, agent_def, agent_id)

    from ..agent.query_engine import QueryEngine
    sub = QueryEngine(**config)
    sub.set_session_id(agent_id)
    parent_engine._child_engines.append(sub)

    try:
        final_event = None
        async for event in sub.submit_message(prompt):
            if event.get("type") == "result":
                final_event = event
                break

        if final_event and final_event.get("is_error"):
            return {
                "status": "failed",
                "agent_id": agent_id,
                "agent_type": agent_def.agent_type,
                "errors": final_event.get("errors", []),
            }

        result_text = (final_event or {}).get("result", "")
        return {
            "status": "completed",
            "agent_id": agent_id,
            "agent_type": agent_def.agent_type,
            "result": result_text[:6000],
            "num_turns": (final_event or {}).get("num_turns", 0),
            "duration_ms": (final_event or {}).get("duration_ms", 0),
        }
    except asyncio.CancelledError:
        return {"status": "cancelled", "agent_id": agent_id, "agent_type": agent_def.agent_type}
    except Exception as e:
        return {"status": "failed", "agent_id": agent_id, "agent_type": agent_def.agent_type, "error": str(e)}
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
    """Run a forked subagent in the background and return immediately."""
    agent_id = str(uuid.uuid4())
    config = create_subagent_context(parent_engine, agent_def, agent_id)

    state = BackgroundAgentState(
        agent_id=agent_id,
        description=description,
        agent_type=agent_def.agent_type,
        prompt=prompt,
    )
    _background_agents[agent_id] = state

    async def _run():
        from ..agent.query_engine import QueryEngine
        sub = QueryEngine(**config)
        sub.set_session_id(agent_id)
        parent_engine._child_engines.append(sub)
        try:
            final_event = None
            async for event in sub.submit_message(prompt):
                if event.get("type") == "result":
                    final_event = event
                    break
            state.updated_at = time.time()
            if final_event and final_event.get("is_error"):
                state.status = "failed"
                state.error = "; ".join(final_event.get("errors", []))
                state.result = final_event
            else:
                state.status = "completed"
                state.result = final_event or {"result": ""}
        except asyncio.CancelledError:
            state.status = "cancelled"
            state.updated_at = time.time()
            state.error = "cancelled"
        except Exception as e:
            state.status = "failed"
            state.updated_at = time.time()
            state.error = str(e)
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
