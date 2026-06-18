"""
MCP config loader — reads from settings.json, .mcp.json, CLI args.
Matching Claude Code's parseMcpConfig / getClaudeCodeMcpConfigs.
"""
import os, json, logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class McpServerConfig:
    """One MCP server config. Matching Claude Code's McpServerConfig."""
    name: str
    type: str = "stdio"           # stdio | sse | http
    command: str = ""             # stdio only
    args: list[str] = field(default_factory=list)  # stdio only
    env: dict[str, str] = field(default_factory=dict)  # stdio only
    url: str = ""                 # sse/http only
    headers: dict[str, str] = field(default_factory=dict)  # sse/http only
    scope: str = "user"           # user | project | local


def load_from_config_json() -> dict[str, McpServerConfig]:
    """Read mcpServers from ~/.db-claude/config.json."""
    config_path = os.path.join(os.path.expanduser("~/.db-claude"), "config.json")
    try:
        with open(config_path) as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        logger.debug("mcp_no_config path=%s", config_path)
        return {}

    servers = data.get("mcpServers", {})
    if not servers:
        return {}

    result = {}
    for name, cfg in servers.items():
        try:
            result[name] = McpServerConfig(
                name=name,
                type=cfg.get("type", "stdio"),
                command=cfg.get("command", ""),
                args=cfg.get("args", []),
                env=cfg.get("env", {}),
                url=cfg.get("url", ""),
                headers=cfg.get("headers", {}),
                scope="user",
            )
        except Exception as e:
            logger.warning("mcp_config_parse_error server=%s error=%s", name, str(e))

    if result:
        logger.info("mcp_config_loaded source=config.json count=%d servers=%s",
                    len(result), list(result.keys()))
    return result


def load_from_project_mcp(project_root: str = None) -> dict[str, McpServerConfig]:
    """Read .claude/.mcp.json from project root."""
    cwd = project_root or os.getcwd()
    mcp_path = os.path.join(cwd, ".claude", ".mcp.json")
    try:
        with open(mcp_path) as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

    servers = data.get("mcpServers", {})
    if not servers:
        return {}

    result = {}
    for name, cfg in servers.items():
        try:
            result[name] = McpServerConfig(
                name=name,
                type=cfg.get("type", "stdio"),
                command=cfg.get("command", ""),
                args=cfg.get("args", []),
                env=cfg.get("env", {}),
                url=cfg.get("url", ""),
                headers=cfg.get("headers", {}),
                scope="project",
            )
        except Exception as e:
            logger.warning("mcp_config_parse_error server=%s error=%s", name, str(e))

    if result:
        logger.info("mcp_config_loaded source=.mcp.json count=%d servers=%s",
                    len(result), list(result.keys()))
    return result


def load_mcp_configs(project_root: str = None) -> dict[str, McpServerConfig]:
    """Load all MCP configs. Project overrides user (same name)."""
    all_configs = {}

    # 1. User config (lower priority)
    for name, cfg in load_from_config_json().items():
        all_configs[name] = cfg

    # 2. Project config (higher priority — overrides user)
    for name, cfg in load_from_project_mcp(project_root).items():
        all_configs[name] = cfg  # Override

    logger.info("mcp_total_configs count=%d", len(all_configs))
    return all_configs
