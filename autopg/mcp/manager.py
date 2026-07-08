"""
MCP connection manager — wrapping langchain-mcp-adapters MultiServerMCPClient.
Matching AutoPG's MCPConnectionManager lifecycle.
"""
import logging
from typing import Any
from langchain_core.tools import BaseTool

logger = logging.getLogger(__name__)


class MCPManager:
    """Manages MCP server connections and tool loading.

    Lifecycle:
        manager = MCPManager()
        tools = await manager.start(configs)
        # ... agent runs ...
        await manager.stop()
    """

    def __init__(self):
        self._client = None
        self._tools: list[BaseTool] = []
        self._prompts: list[Any] = []
        self._status: dict[str, str] = {}  # server_name → pending|connected|failed

    @property
    def tools(self) -> list[BaseTool]:
        return list(self._tools)

    @property
    def status(self) -> dict[str, str]:
        return dict(self._status)

    @property
    def prompts(self) -> list[Any]:
        return list(self._prompts)

    @property
    def is_connected(self) -> bool:
        return self._client is not None

    def server_names(self) -> list[str]:
        return list(self._status.keys())

    async def start(self, configs: dict) -> list[BaseTool]:
        """Connect to all MCP servers and load tools.

        Args:
            configs: dict[name, McpServerConfig]

        Returns:
            list of BaseTool with mcp__<server>__<tool> names
        """
        if not configs:
            logger.debug("mcp_no_servers")
            return []

        # Build connections dict for MultiServerMCPClient
        connections = {}
        for name, cfg in configs.items():
            self._status[name] = "pending"
            if cfg.type == "stdio":
                connections[name] = {
                    "command": cfg.command,
                    "args": list(cfg.args),
                    "env": dict(cfg.env),
                    "transport": "stdio",
                }
            elif cfg.type == "sse":
                connections[name] = {
                    "url": cfg.url,
                    "transport": "sse",
                }
            else:
                logger.warning("mcp_unsupported_type server=%s type=%s", name, cfg.type)
                self._status[name] = "failed"
                continue

        if not connections:
            return []

        try:
            from langchain_mcp_adapters.client import MultiServerMCPClient
            self._client = MultiServerMCPClient(connections=connections)

            # Load tools with mcp__<server>__ prefix.  langchain-mcp-adapters
            # >=0.1.0 no longer supports using MultiServerMCPClient as an
            # async context manager; get_tools() opens the configured sessions
            # as needed and returns LangChain-compatible tools.
            raw_tools = await self._client.get_tools()
            prefixed_tools = []
            for tool in raw_tools:
                metadata = getattr(tool, 'metadata', None) or {}
                server = metadata.get('server_name', '')
                if not server:
                    # Infer server from tool name if metadata missing
                    for sname in connections:
                        if sname in tool.name:
                            server = sname
                            break
                if not server:
                    server = list(connections.keys())[0]

                tool.name = f"mcp__{server}__{tool.name}"
                prefixed_tools.append(tool)
                if server in self._status:
                    self._status[server] = "connected"

            self._tools = prefixed_tools
            await self.load_prompts()
            logger.info("mcp_connected servers=%d tools=%d prompts=%d status=%s",
                        len(connections), len(prefixed_tools), len(self._prompts), self._status)

            return prefixed_tools

        except Exception as e:
            logger.exception("mcp_connect_failed error=%s", str(e))
            for name in connections:
                if self._status.get(name) == "pending":
                    self._status[name] = "failed"
            return []

    async def load_prompts(self) -> list[Any]:
        """Load MCP prompts and register prompt-like skills."""
        self._prompts = []
        if not self._client:
            return []
        try:
            from ..skills.loader import SkillDef, skill_registry

            for server in self._status:
                if self._status.get(server) == "failed":
                    continue
                try:
                    async with self._client.session(server) as session:
                        listed = await session.list_prompts()
                        for prompt in getattr(listed, "prompts", []):
                            name = prompt.name
                            loaded = await session.get_prompt(name)
                            messages = getattr(loaded, "messages", loaded)
                            body = "\n\n".join(str(getattr(m, "content", m)) for m in messages)
                            meta, clean_body = self._parse_skill_frontmatter(body)
                            skill_registry.register(SkillDef(
                                name=meta.get("name", name),
                                description=meta.get("description", getattr(prompt, "description", "") or name),
                                prompt=clean_body,
                                when_to_use=meta.get("when_to_use", ""),
                                argument_hint=meta.get("argument_hint", ""),
                                tools=meta.get("tools", []) if isinstance(meta.get("tools"), list) else [],
                                source=f"mcp:{server}",
                                file_path=f"mcp://{server}/prompts/{name}",
                            ))
                            self._prompts.append(prompt)
                except Exception as exc:
                    logger.warning("mcp_prompt_load_failed server=%s error=%s", server, exc)
        except Exception as exc:
            logger.warning("mcp_prompt_registry_failed error=%s", exc)
        return list(self._prompts)

    @staticmethod
    def _parse_skill_frontmatter(content: str) -> tuple[dict, str]:
        import yaml

        if not content.startswith("---"):
            return {}, content
        parts = content.split("---", 2)
        if len(parts) < 3:
            return {}, content
        try:
            meta = yaml.safe_load(parts[1]) or {}
        except Exception:
            meta = {}
        return meta, parts[2].strip()


    async def stop(self):
        """Close all MCP connections."""
        if self._client:
            self._client = None
            self._tools = []
            self._prompts = []
            logger.info("mcp_stopped")
