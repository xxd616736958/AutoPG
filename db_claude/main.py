#!/usr/bin/env python3
"""
db-claude: An intelligent coding agent built with LangChain and LangGraph.
Architecturally identical to Claude Code, reimplemented in Python.

Main entry point — mirrors Claude Code's main.tsx and dev-entry.ts.
"""
import os
import sys
import asyncio
import argparse
from pathlib import Path

# Ensure we can import from the package
sys.path.insert(0, str(Path(__file__).parent.parent))

from db_claude.utils.config import get_global_config, load_config, save_config
from db_claude.tools import create_default_tools
from db_claude.agent.query_loop import QueryEngine
from db_claude.cli.commands import SlashCommandHandler
from db_claude.cli.repl import ReplInterface
from db_claude.context.memory import MemoryManager


def parse_args():
    """Parse command-line arguments, mirroring Claude Code's CLI flags."""
    parser = argparse.ArgumentParser(
        prog="db-claude",
        description="db-claude: Intelligent Coding Agent (Python/LangChain/LangGraph)",
    )

    parser.add_argument(
        "prompt",
        nargs="?",
        help="Initial prompt to send (non-interactive mode)",
    )
    parser.add_argument(
        "--version", "-v",
        action="store_true",
        help="Show version and exit",
    )
    parser.add_argument(
        "--model", "-m",
        default=None,
        help="Model to use (e.g., deepseek-v4-flash, claude-sonnet-4-6)",
    )
    parser.add_argument(
        "--provider",
        default=None,
        choices=["anthropic", "deepseek"],
        help="LLM provider (anthropic or deepseek)",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="API key for the provider",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="Base URL for the API endpoint",
    )
    parser.add_argument(
        "--fallback-model",
        default=None,
        help="Fallback model on overload",
    )
    parser.add_argument(
        "--max-turns",
        type=int,
        default=None,
        help="Maximum number of agent turns",
    )
    parser.add_argument(
        "--max-budget-usd",
        type=float,
        default=None,
        help="Maximum USD budget for API calls",
    )
    parser.add_argument(
        "--permission-mode",
        default=None,
        choices=["default", "accept_edits", "bypass", "plan"],
        help="Permission mode for tool execution",
    )
    parser.add_argument(
        "--print", "-p",
        action="store_true",
        help="Print response and exit (non-interactive)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose output",
    )
    parser.add_argument(
        "--cwd",
        default=None,
        help="Working directory",
    )
    parser.add_argument(
        "--system-prompt",
        default=None,
        help="Custom system prompt (replaces default)",
    )
    parser.add_argument(
        "--append-system-prompt",
        default=None,
        help="Additional text appended to system prompt",
    )
    parser.add_argument(
        "--init",
        action="store_true",
        help="Initialize a new CLAUDE.md for the project",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume the last conversation",
    )

    return parser.parse_args()


def _build_engine(args, config, non_interactive: bool = False) -> QueryEngine:
    """Build a QueryEngine from args + config. Shared by interactive and print modes."""
    tools = create_default_tools()
    tools_list = tools.list_enabled()

    # Resolve config: CLI args > env vars > config file
    provider = args.provider or config.provider
    model = args.model or config.model
    api_key = args.api_key or config.api_key
    base_url = args.base_url or config.base_url

    # Fallback: if provider is deepseek and no base_url, set default
    if provider == "deepseek" and not base_url:
        base_url = "https://api.deepseek.com/v1"

    return QueryEngine(
        tools=tools_list,
        model_name=model,
        fallback_model=args.fallback_model or config.fallback_model,
        cwd=args.cwd or config.cwd,
        max_turns=args.max_turns or config.max_turns,
        max_budget_usd=args.max_budget_usd or config.max_budget_usd,
        permission_mode=args.permission_mode or config.permission_mode,
        custom_system_prompt=args.system_prompt,
        append_system_prompt=args.append_system_prompt,
        is_non_interactive_session=non_interactive,
        provider=provider,
        api_key=api_key,
        base_url=base_url,
    )


async def run_interactive(args, config):
    """Run the interactive REPL mode."""
    cmd_handler = SlashCommandHandler()
    engine = _build_engine(args, config, non_interactive=False)

    # Print startup info
    print(f"\n  Provider: {config.provider}")
    print(f"  Model:    {engine.model_name}")
    print(f"  API Key:  {'configured' if engine.api_key else 'not set'}")
    print()

    repl = ReplInterface(
        query_engine=engine,
        config=config,
        command_handler=cmd_handler,
    )
    await repl.run()


async def run_print_mode(args, config):
    """Run in non-interactive print mode (mirrors --print / -p)."""
    engine = _build_engine(args, config, non_interactive=True)

    prompt = args.prompt or sys.stdin.read().strip()
    if not prompt:
        print("Error: No prompt provided. Use --prompt or pipe input.", file=sys.stderr)
        sys.exit(1)

    try:
        result = await engine.submit_message(prompt)
        if result.get("type") == "result":
            text = result.get("result", "")
            if text:
                print(text)
            else:
                import json
                print(json.dumps(result, indent=2, ensure_ascii=False))
        sys.exit(0 if not result.get("is_error") else 1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def main():
    """Main entry point."""
    args = parse_args()

    # Show version
    if args.version:
        from db_claude import __version__
        print(f"db-claude v{__version__}")
        sys.exit(0)

    # Initialize CLAUDE.md
    if args.init:
        _init_claude_md(args)
        sys.exit(0)

    # Load config
    config = load_config()

    # Apply CLI overrides to config (so slash commands see updates)
    if args.model:
        config.model = args.model
    if args.provider:
        config.provider = args.provider
    if args.api_key:
        config.api_key = args.api_key
    if args.base_url:
        config.base_url = args.base_url
    if args.permission_mode:
        config.permission_mode = args.permission_mode

    # Check for API key
    if not config.api_key:
        provider_keys = {
            "deepseek": "DEEPSEEK_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
        }
        env_var = provider_keys.get(config.provider, "API_KEY")
        print(
            f"Warning: No API key configured for {config.provider}.\n"
            f"  Set {env_var} environment variable, or\n"
            f"  Use --api-key flag, or\n"
            f"  Configure in ~/.db-claude/config.json",
            file=sys.stderr,
        )

    # Run in appropriate mode
    if args.print or (args.prompt and not sys.stdin.isatty()):
        asyncio.run(run_print_mode(args, config))
    else:
        asyncio.run(run_interactive(args, config))


def _init_claude_md(args):
    """Initialize a CLAUDE.md file for the project."""
    cwd = args.cwd or os.getcwd()
    claude_md_path = os.path.join(cwd, "CLAUDE.md")

    if os.path.exists(claude_md_path):
        print(f"CLAUDE.md already exists at {claude_md_path}")
        sys.exit(0)

    template = f"""# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

[Describe your project here]

## Build & Development Commands

```
# Build
# Test
# Run
```

## Code Style

[Describe your code style conventions]

## Testing

[Describe your testing approach]

## Architecture Notes

[Document important architectural decisions]
"""

    with open(claude_md_path, "w") as f:
        f.write(template)

    print(f"Created CLAUDE.md at {claude_md_path}")
    print("Edit it to provide guidance to db-claude about your project.")


if __name__ == "__main__":
    main()
