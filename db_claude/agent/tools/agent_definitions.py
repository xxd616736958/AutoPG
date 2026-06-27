"""
Agent definitions — matching Claude Code's loadAgentsDir.ts and builtInAgents.ts.
Each AgentDefinition is a "config file" for a subagent type.
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AgentDefinition:
    """One agent type definition. Claude Code: AgentDefinition in loadAgentsDir.ts."""
    agent_type: str                    # 'general-purpose' | 'Explore' | 'Plan' | custom
    description: str                   # one-line hook shown to the model
    when_to_use: str                   # guidance on when to pick this agent
    system_prompt: str                 # subagent's custom system prompt ("" = inherit parent)
    tools: list[str] = field(default_factory=lambda: ["*"])  # tool whitelist, '*' = all
    disallowed_tools: list[str] = field(default_factory=list)  # tools explicitly blocked
    model: str = "inherit"            # model name or "inherit"
    max_turns: int = 50               # max agent turns per query
    permission_mode: str = "default"  # permission mode for subagent
    source: str = "built-in"          # 'built-in' | 'custom' | 'plugin'
    base_dir: str = ""                # directory where the agent definition file lives


# ── Built-in agents (Claude Code: builtInAgents.ts) ──

EXPLORE_AGENT = AgentDefinition(
    agent_type="Explore",
    description="Read-only search agent for broad fan-out searches",
    when_to_use=(
        "When answering would mean reading across several files, directories, "
        "or naming conventions and you only need the conclusion, not the file dumps. "
        "Specify search breadth: 'medium' for moderate exploration, 'very thorough' "
        "for multiple locations and naming conventions."
    ),
    system_prompt=(
        "You are a read-only search agent. Your ONLY job is to find information "
        "and report it back concisely.\n\n"
        "CRITICAL RULES:\n"
        "- You CANNOT write, edit, or delete files. No Bash, no Write, no Edit.\n"
        "- Your ONLY tools are Read, Glob, Grep, WebSearch, WebFetch.\n"
        "- Do NOT suggest code changes or fixes. Only report what you find.\n"
        "- Be thorough: search multiple locations, naming conventions, and patterns.\n"
        "- Return structured results with file paths and line numbers.\n"
        "- If you find nothing, say so clearly — don't fabricate results."
    ),
    tools=["read", "glob", "grep", "web_search", "web_fetch"],
    model="inherit",
    max_turns=20,
    permission_mode="default",
    source="built-in",
)

PLAN_AGENT = AgentDefinition(
    agent_type="Plan",
    description="Software architect agent for designing implementation plans",
    when_to_use=(
        "Before implementing non-trivial features requiring architectural decisions, "
        "multi-file changes, or when multiple valid approaches exist."
    ),
    system_prompt=(
        "You are a software architect. Design implementation plans for coding tasks.\n\n"
        "Your output should be a structured plan covering:\n"
        "1. Overview: what the feature does, key constraints\n"
        "2. Affected files: specific paths, new files needed\n"
        "3. Step-by-step approach: ordered implementation tasks\n"
        "4. Architectural decisions: which patterns, libraries, trade-offs\n"
        "5. Testing strategy: what to test, edge cases\n"
        "6. Risk assessment: what could go wrong, mitigation\n\n"
        "CRITICAL: You are in Plan mode. Do NOT write code. Do NOT edit files. "
        "Only read and design. Output your plan for user approval."
    ),
    tools=["read", "glob", "grep"],
    model="inherit",
    max_turns=30,
    permission_mode="plan",
    source="built-in",
)

GENERAL_PURPOSE_AGENT = AgentDefinition(
    agent_type="general-purpose",
    description="Catch-all agent for complex multi-step tasks",
    when_to_use=(
        "For complex questions, code search, and multi-step tasks. "
        "Use when a more specific agent type is not available."
    ),
    system_prompt="",  # Inherits parent system prompt
    tools=["*"],
    disallowed_tools=[
        "agent",           # No recursive subagent spawning
        "ask_user_question", # Cannot ask user questions
        "task_stop",        # Cannot stop tasks
        "workflow",        # Cannot orchestrate workflows
        "enter_plan_mode",   # Cannot enter plan mode
        "exit_plan_mode",    # Cannot exit plan mode
        "skill",           # Cannot invoke skills
    ],
    model="inherit",
    max_turns=50,
    permission_mode="default",
    source="built-in",
)

# ── Registry ──

_BUILTIN_AGENTS: dict[str, AgentDefinition] = {
    "general-purpose": GENERAL_PURPOSE_AGENT,
    "Explore": EXPLORE_AGENT,
    "Plan": PLAN_AGENT,
}

_CUSTOM_AGENTS: dict[str, AgentDefinition] = {}


def find_agent_definition(agent_type: str) -> Optional[AgentDefinition]:
    """Find an agent definition by type name. Checks custom first, then built-in."""
    if agent_type in _CUSTOM_AGENTS:
        return _CUSTOM_AGENTS[agent_type]
    return _BUILTIN_AGENTS.get(agent_type)


def register_custom_agent(agent_def: AgentDefinition):
    """Register a custom agent definition (from CLAUDE.md or agents/ dir)."""
    _CUSTOM_AGENTS[agent_def.agent_type] = agent_def


def list_available_agents() -> list[AgentDefinition]:
    """List all available agent definitions."""
    all_agents = list(_BUILTIN_AGENTS.values()) + list(_CUSTOM_AGENTS.values())
    # Deduplicate by agent_type
    seen = set()
    result = []
    for a in all_agents:
        if a.agent_type not in seen:
            seen.add(a.agent_type)
            result.append(a)
    return result


def get_allowed_agent_types(tools: list = None) -> list[str]:
    """Return agent type names the model is allowed to invoke."""
    return list(_BUILTIN_AGENTS.keys()) + list(_CUSTOM_AGENTS.keys())
