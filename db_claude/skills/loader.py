"""
Skill loader — scan .md files with YAML frontmatter from skill directories.
"""
import os, re, glob, logging, yaml
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class SkillDef:
    """One skill definition. Same structure as Claude Code's PromptCommand skill."""
    name: str
    description: str
    prompt: str                      # Body text (below frontmatter)
    when_to_use: str = ""            # Guidance on when model should invoke
    argument_hint: str = ""          # Argument hint for user display
    tools: list[str] = field(default_factory=list)  # Allowed tools (empty = all)
    model: str = "inherit"           # Model override
    max_turns: int = 30              # Max turns for skill execution
    source: str = "user"             # user / project / bundled
    file_path: str = ""              # Source .md file path


class SkillRegistry:
    """In-memory registry of all loaded skills."""

    def __init__(self):
        self._skills: dict[str, SkillDef] = {}

    def register(self, skill: SkillDef):
        existing = self._skills.get(skill.name)
        if existing:
            # Project skills override user skills; bundled are lowest priority
            priority = {"bundled": 0, "user": 1, "project": 2}
            if priority.get(skill.source, 0) <= priority.get(existing.source, 0):
                return  # Keep existing (higher priority)
        self._skills[skill.name] = skill

    def get(self, name: str) -> Optional[SkillDef]:
        return self._skills.get(name)

    def list_all(self) -> list[SkillDef]:
        return list(self._skills.values())

    def __len__(self) -> int:
        return len(self._skills)


def _parse_frontmatter(content: str) -> tuple[dict, str]:
    """Parse YAML frontmatter from markdown. Returns (meta, body)."""
    if not content.startswith("---"):
        return {}, content
    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}, content
    try:
        meta = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        meta = {}
    return meta, parts[2].strip()


def load_skills_from_dir(directory: str, source: str) -> list[SkillDef]:
    """Scan a directory for .md skill files."""
    if not os.path.isdir(directory):
        return []
    skills = []
    for fpath in sorted(glob.glob(os.path.join(directory, "*.md"))):
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                content = f.read()
            meta, body = _parse_frontmatter(content)
            if not meta.get("name") or not meta.get("description"):
                logger.debug("skill_skip_no_metadata path=%s", fpath)
                continue

            skill = SkillDef(
                name=meta["name"],
                description=meta["description"],
                prompt=body,
                when_to_use=meta.get("when_to_use", ""),
                argument_hint=meta.get("argument_hint", ""),
                tools=meta.get("tools", []) if isinstance(meta.get("tools"), list) else [],
                model=meta.get("model", "inherit"),
                max_turns=meta.get("max_turns", 30),
                source=source,
                file_path=fpath,
            )
            skills.append(skill)
            logger.info("skill_loaded name=%s source=%s desc=%s", skill.name, source, skill.description[:60])
        except Exception as e:
            logger.warning("skill_parse_error path=%s error=%s", fpath, str(e))
    return skills


def load_all_skills(project_root: str = None) -> SkillRegistry:
    """Scan all skill directories and populate global skill_registry.

    Priority: project > user > bundled.
    """
    # Clear and repopulate in-place (don't reassign — importers hold references)
    skill_registry._skills.clear()

    # 1. Bundled skills (lowest priority)
    bundled_dir = os.path.join(os.path.dirname(__file__), "bundled")
    for skill in load_skills_from_dir(bundled_dir, "bundled"):
        skill_registry.register(skill)

    # 2. User skills (~/.db-claude/skills/)
    user_dir = os.path.join(os.path.expanduser("~/.db-claude"), "skills")
    for skill in load_skills_from_dir(user_dir, "user"):
        skill_registry.register(skill)

    # 3. Project skills (.claude/skills/) (highest priority)
    cwd = project_root or os.getcwd()
    project_dir = os.path.join(cwd, ".claude", "skills")
    for skill in load_skills_from_dir(project_dir, "project"):
        skill_registry.register(skill)

    logger.info("skills_loaded total=%d bundled=%d user=%d project=%d",
                len(skill_registry),
                sum(1 for s in skill_registry.list_all() if s.source == "bundled"),
                sum(1 for s in skill_registry.list_all() if s.source == "user"),
                sum(1 for s in skill_registry.list_all() if s.source == "project"))
    return skill_registry


# Global registry — initialized at startup
skill_registry = SkillRegistry()
