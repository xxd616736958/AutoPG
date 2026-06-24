"""
MCP config loader — reads from user config, project config, and built-in DB tuning MCP.
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
    scope: str = "user"           # user | project | local | builtin


def _parse_server_config(name: str, cfg: dict, scope: str) -> McpServerConfig:
    return McpServerConfig(
        name=name,
        type=cfg.get("type", "stdio"),
        command=cfg.get("command", ""),
        args=cfg.get("args", []),
        env=cfg.get("env", {}),
        url=cfg.get("url", ""),
        headers=cfg.get("headers", {}),
        scope=scope,
    )


def load_builtin_postgres_mcp() -> dict[str, McpServerConfig]:
    """Create the built-in postgres-mcp config for the DB tuning agent.

    The project is intended to work out of the box as a database tuning agent.
    A user or project mcpServers.postgres entry can still override this config.
    """
    enabled = os.environ.get("DB_CLAUDE_ENABLE_POSTGRES_MCP", "true").lower()
    if enabled in ("0", "false", "no", "off"):
        return {}

    database_uri = os.environ.get("DB_CLAUDE_DATABASE_URI") or os.environ.get("DATABASE_URI")
    if not database_uri:
        user = os.environ.get("USER") or "postgres"
        database_uri = f"postgresql://{user}@localhost:5432/db_agent"

    access_mode = os.environ.get("DB_CLAUDE_POSTGRES_ACCESS_MODE", "restricted")
    command = os.environ.get("DB_CLAUDE_POSTGRES_MCP_COMMAND", "uvx")
    package = os.environ.get("DB_CLAUDE_POSTGRES_MCP_PACKAGE", "postgres-mcp")

    cfg = McpServerConfig(
        name="postgres",
        type="stdio",
        command=command,
        args=[package, f"--access-mode={access_mode}"],
        env={"DATABASE_URI": database_uri},
        scope="builtin",
    )
    logger.info("mcp_config_loaded source=builtin-postgres server=postgres database_uri=%s access_mode=%s",
                database_uri, access_mode)
    return {"postgres": cfg}


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
            result[name] = _parse_server_config(name, cfg, "user")
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
            result[name] = _parse_server_config(name, cfg, "project")
        except Exception as e:
            logger.warning("mcp_config_parse_error server=%s error=%s", name, str(e))

    if result:
        logger.info("mcp_config_loaded source=.mcp.json count=%d servers=%s",
                    len(result), list(result.keys()))
    return result


def load_mcp_configs(project_root: str = None) -> dict[str, McpServerConfig]:
    """Load all MCP configs. Priority: builtin < user < project."""
    all_configs = {}

    # 1. Built-in postgres-mcp for database tuning agent (lowest priority)
    for name, cfg in load_builtin_postgres_mcp().items():
        all_configs[name] = cfg

    # 2. User config
    for name, cfg in load_from_config_json().items():
        all_configs[name] = cfg

    # 3. Project config (highest priority — overrides user/builtin)
    for name, cfg in load_from_project_mcp(project_root).items():
        all_configs[name] = cfg

    logger.info("mcp_total_configs count=%d", len(all_configs))
    return all_configs
