"""
Slash command system for db-claude.
Architecturally identical to Claude Code's slash commands (src/commands.ts).
"""
from typing import Optional, Callable
from dataclasses import dataclass


@dataclass
class SlashCommand:
    """A slash command definition."""
    name: str
    description: str
    handler: Callable
    aliases: list[str] = None

    def __post_init__(self):
        if self.aliases is None:
            self.aliases = []


class SlashCommandHandler:
    """
    Handles slash commands like /help, /model, /clear, /compact, etc.
    Mirrors Claude Code's command system (src/commands.ts).
    """

    def __init__(self):
        self._commands: dict[str, SlashCommand] = {}
        self._register_defaults()

    def _register_defaults(self):
        """Register built-in slash commands."""
        self.register(SlashCommand(
            name="help",
            description="Show available commands and help",
            handler=self._cmd_help,
            aliases=["h", "?"],
        ))
        self.register(SlashCommand(
            name="model",
            description="Show or change the current model",
            handler=self._cmd_model,
        ))
        self.register(SlashCommand(
            name="clear",
            description="Clear the conversation history",
            handler=self._cmd_clear,
        ))
        self.register(SlashCommand(
            name="compact",
            description="Manually trigger context compaction",
            handler=self._cmd_compact,
        ))
        self.register(SlashCommand(
            name="config",
            description="Show or change configuration",
            handler=self._cmd_config,
        ))
        self.register(SlashCommand(
            name="memory",
            description="Manage persistent memory",
            handler=self._cmd_memory,
        ))
        self.register(SlashCommand(
            name="exit",
            description="Exit db-claude",
            handler=self._cmd_exit,
            aliases=["quit", "q"],
        ))
        self.register(SlashCommand(
            name="version",
            description="Show db-claude version",
            handler=self._cmd_version,
        ))
        self.register(SlashCommand(
            name="cost",
            description="Show token usage and cost",
            handler=self._cmd_cost,
        ))
        self.register(SlashCommand(
            name="permissions",
            description="Show or change permission mode",
            handler=self._cmd_permissions,
        ))
        self.register(SlashCommand(
            name="session",
            description="Show session info, list sessions, or resume",
            handler=self._cmd_session,
            aliases=["sessions"],
        ))

    def register(self, command: SlashCommand):
        """Register a slash command."""
        self._commands[command.name] = command
        for alias in command.aliases:
            self._commands[alias] = command

    def get(self, name: str) -> Optional[SlashCommand]:
        """Get a command by name."""
        return self._commands.get(name)

    def is_slash_command(self, text: str) -> bool:
        """Check if text starts with a slash command."""
        text = text.strip()
        if not text.startswith("/"):
            return False
        cmd_name = text.split()[0][1:]  # Remove leading /
        return cmd_name in self._commands

    def handle(self, text: str, context: dict) -> str:
        """Handle a slash command and return the result."""
        text = text.strip()
        if not text.startswith("/"):
            return None

        parts = text[1:].split()  # Remove leading /
        cmd_name = parts[0]
        args = parts[1:] if len(parts) > 1 else []

        command = self._commands.get(cmd_name)
        if not command:
            return f"Unknown command: /{cmd_name}. Type /help for available commands."

        try:
            return command.handler(args, context)
        except Exception as e:
            return f"Command error: {str(e)}"

    # -- Built-in command handlers --

    def _cmd_help(self, args: list, context: dict) -> str:
        """Show available commands."""
        seen = set()
        lines = ["Available commands:", ""]
        for name, cmd in sorted(self._commands.items()):
            if name in seen:
                continue
            seen.add(name)
            aliases_str = f" (aliases: {', '.join('/' + a for a in cmd.aliases)})" if cmd.aliases else ""
            lines.append(f"  /{name}{aliases_str} — {cmd.description}")
        return "\n".join(lines)

    def _cmd_model(self, args: list, context: dict) -> str:
        """Show or change the model."""
        if args:
            new_model = args[0]
            context["config"].model = new_model
            return f"Model changed to: {new_model}"
        return f"Current model: {context.get('config', {}).get('model', 'unknown')}"

    def _cmd_clear(self, args: list, context: dict) -> str:
        """Clear conversation history."""
        context["messages_clear"] = True
        return "Conversation history cleared."

    def _cmd_compact(self, args: list, context: dict) -> str:
        """Manually trigger compaction."""
        context["trigger_compact"] = True
        return "Context compaction triggered. Previous messages will be summarized."

    def _cmd_config(self, args: list, context: dict) -> str:
        """Show or change configuration."""
        config = context.get("config", {})
        if not args:
            lines = ["Current configuration:", ""]
            for key, value in vars(config).items():
                if not key.startswith("_") and key != "api_key":
                    lines.append(f"  {key}: {value}")
            lines.append(f"  api_key: {'sk-...' + config.api_key[-8:] if config.api_key else 'not set'}")
            return "\n".join(lines)
        return "Config set commands: /config key=value"

    def _cmd_memory(self, args: list, context: dict) -> str:
        """Manage memories."""
        memory_manager = context.get("memory_manager")
        if not memory_manager:
            return "Memory system not initialized."
        memories = memory_manager.list_memories()
        if not memories:
            return "No memories stored for this project."
        lines = ["Stored memories:", ""]
        for mem in memories:
            lines.append(f"  - {mem['title']} ({mem['type']}): {mem['description']}")
        return "\n".join(lines)

    def _cmd_exit(self, args: list, context: dict) -> str:
        """Exit the application."""
        context["should_exit"] = True
        return "Goodbye!"

    def _cmd_version(self, args: list, context: dict) -> str:
        """Show version."""
        from .. import __version__
        return f"db-claude v{__version__}"

    def _cmd_cost(self, args: list, context: dict) -> str:
        """Show usage stats."""
        engine = context.get("query_engine")
        if engine:
            usage = engine.total_usage
            return (
                f"Token usage:\n"
                f"  Input: {usage.get('input_tokens', 0):,}\n"
                f"  Output: {usage.get('output_tokens', 0):,}\n"
                f"  Cache reads: {usage.get('cache_read_tokens', 0):,}\n"
                f"  Cache creations: {usage.get('cache_creation_tokens', 0):,}"
            )
        return "No usage data available."

    def _cmd_permissions(self, args: list, context: dict) -> str:
        """Show or change permission mode."""
        config = context.get("config", {})
        if args:
            mode = args[0]
            valid_modes = ["default", "accept_edits", "bypass", "plan"]
            if mode not in valid_modes:
                return f"Invalid mode. Choose from: {', '.join(valid_modes)}"
            config.permission_mode = mode
            return f"Permission mode changed to: {mode}"
        return f"Current permission mode: {config.permission_mode}"

    def _cmd_session(self, args: list, context: dict) -> str:
        """Show session info or list sessions."""
        from ..utils.session import list_sessions, get_last_session_id, load_session

        engine = context.get("query_engine")
        if not engine:
            return "No active session."

        if args and args[0] == "list":
            sessions = list_sessions(limit=20)
            if not sessions:
                return "No saved sessions."
            lines = [f"{'SESSION ID':<38} {'MSGS':>5}  SAVED AT"]
            for s in sessions:
                sid = s["session_id"][:36]
                msgs = s["message_count"]
                saved = s["saved_at"][:19]
                marker = " ← current" if s["session_id"] == engine.session_id else ""
                lines.append(f"{sid:<38} {msgs:>5}  {saved}{marker}")
            return "\n".join(lines)

        sid = engine.session_id
        msgs = len(engine.mutable_messages)
        usage = engine.total_usage
        return (
            f"Current session: {sid[:16]}...\n"
            f"Messages: {msgs}\n"
            f"Input tokens:  {usage.get('input_tokens', 0):,}\n"
            f"Output tokens: {usage.get('output_tokens', 0):,}\n"
            f"Auto-save:     enabled\n"
            f"\nUse /session list to view saved sessions."
        )
