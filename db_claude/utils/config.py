"""
Configuration management for db-claude.
Handles settings from ~/.db-claude/config.json, environment variables, and CLI args.
Architecturally mirrors Claude Code's config system (src/utils/config.ts).
"""
import os
import json
from typing import Optional, Any
from dataclasses import dataclass, field


@dataclass
class GlobalConfig:
    """Global configuration, mirroring getGlobalConfig() in config.ts."""
    # Provider: "anthropic" or "deepseek"
    provider: str = "deepseek"

    # Model name
    model: str = "deepseek-v4-flash"
    fallback_model: Optional[str] = None

    # API credentials
    api_key: Optional[str] = None
    base_url: Optional[str] = "https://api.deepseek.com/v1"

    # Behavior
    permission_mode: str = "default"
    verbose: bool = False
    theme: str = "dark"

    # Limits
    max_turns: Optional[int] = None
    max_budget_usd: Optional[float] = None

    # Working directory
    cwd: str = field(default_factory=os.getcwd)


def get_config_path() -> str:
    """Get the path to the config file."""
    config_dir = os.environ.get(
        "DB_CLAUDE_CONFIG_DIR",
        os.path.expanduser("~/.db-claude"),
    )
    return os.path.join(config_dir, "config.json")


def load_config() -> GlobalConfig:
    """Load configuration from file, then override with environment variables."""
    config = GlobalConfig()

    # Load from file
    config_path = get_config_path()
    if os.path.exists(config_path):
        try:
            with open(config_path, "r") as f:
                data = json.load(f)
            for key, value in data.items():
                if hasattr(config, key):
                    setattr(config, key, value)
        except (json.JSONDecodeError, IOError):
            pass

    # Priority order: config file < provider-specific env < DB_CLAUDE_* env
    # DB_CLAUDE_* vars always win (user explicitly set them for db-claude)
    # Provider-specific vars only apply when they match the current provider

    def _apply_env(env_var: str, attr_name: str, converter=None):
        value = os.environ.get(env_var)
        if value is not None:
            if converter:
                value = converter(value)
            setattr(config, attr_name, value)

    # 1. Provider-specific API key/base_url (only if provider matches)
    if config.provider == "deepseek":
        _apply_env("DEEPSEEK_API_KEY", "api_key")
        _apply_env("DEEPSEEK_BASE_URL", "base_url")
    elif config.provider == "anthropic":
        _apply_env("ANTHROPIC_API_KEY", "api_key")
        _apply_env("ANTHROPIC_BASE_URL", "base_url")

    # 2. DB_CLAUDE_* universal overrides (always win — highest priority)
    _apply_env("DB_CLAUDE_PROVIDER", "provider")
    _apply_env("DB_CLAUDE_MODEL", "model")
    _apply_env("DB_CLAUDE_FALLBACK_MODEL", "fallback_model")
    _apply_env("DB_CLAUDE_API_KEY", "api_key")
    _apply_env("DB_CLAUDE_BASE_URL", "base_url")
    _apply_env("DB_CLAUDE_PERMISSION_MODE", "permission_mode")
    _apply_env("DB_CLAUDE_MAX_TURNS", "max_turns", converter=int)
    _apply_env("DB_CLAUDE_MAX_BUDGET_USD", "max_budget_usd", converter=float)

    return config


def save_config(config: GlobalConfig):
    """Save configuration to file."""
    config_path = get_config_path()
    config_dir = os.path.dirname(config_path)
    os.makedirs(config_dir, exist_ok=True)

    data = {
        "provider": config.provider,
        "model": config.model,
        "fallback_model": config.fallback_model,
        "api_key": config.api_key,
        "base_url": config.base_url,
        "permission_mode": config.permission_mode,
        "verbose": config.verbose,
        "theme": config.theme,
        "max_turns": config.max_turns,
        "max_budget_usd": config.max_budget_usd,
    }

    with open(config_path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# Global config instance
_global_config: Optional[GlobalConfig] = None


def get_global_config() -> GlobalConfig:
    """Get the global config, loading if needed."""
    global _global_config
    if _global_config is None:
        _global_config = load_config()
    return _global_config
