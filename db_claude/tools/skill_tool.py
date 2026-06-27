"""Skill tool — matching Claude Code's SkillTool. Injects prompt as user message."""
import json, logging, time
from pydantic import Field
from langchain_core.tools import tool

from ..skills.loader import skill_registry

logger = logging.getLogger(__name__)


@tool
async def skill(
    skill: str = Field(description="Name of a skill from the available-skills list. Do not guess names."),
    args: str = Field(default=None, description="Optional arguments for the skill"),
) -> str:
    """Execute a skill within the main conversation. Skills provide specialized capabilities.

    When users reference a slash command or /<something>, they are referring to a skill.
    When a skill matches the user's request, invoke this tool BEFORE generating any response.
    NEVER mention a skill without actually calling this tool.
    Do not invoke a skill that is already running.
    Do not use this tool for built-in CLI commands like /help or /clear.
    """
    # Suppress duplicate skill calls in the same task. Models may emit multiple
    # identical skill tool calls before the first result is injected into state.
    try:
        import os
        marker = f"DB_CLAUDE_SKILL_RUNNING_{skill}"
        ts = float(os.environ.get(marker, "0") or "0")
        if ts and time.time() - ts < 30:
            return json.dumps({
                "status": "already_loaded",
                "skill": skill,
                "instruction": f"The {skill} skill is already loaded/running. Continue executing its instructions; do not call the skill tool again.",
            })
        os.environ[marker] = str(time.time())
    except Exception:
        pass

    skill_def = skill_registry.get(skill)
    if not skill_def:
        available = [s.name for s in skill_registry.list_all()]
        logger.info("skill_not_found name=%s available=%s", skill, available)
        return json.dumps({"error": f"Skill not found: '{skill}'. Available: {', '.join(available)}"})

    # Replace {args} placeholder with user-provided arguments
    prompt = skill_def.prompt
    if args:
        prompt = prompt.replace("{args}", args)
    else:
        prompt = prompt.replace("{args}", "")

    logger.info("skill_invoked name=%s source=%s prompt_len=%d args=%s",
                skill, skill_def.source, len(prompt), args or "")

    return json.dumps({
        "status": "loaded",
        "skill": skill,
        "source": skill_def.source,
        "prompt": prompt,
        "instruction": "Follow the skill instructions above to complete the task.",
    })
