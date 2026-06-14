"""
Glob tool for db-claude.
Architecturally identical to Claude Code's GlobTool.
"""
import os
import fnmatch
from typing import Type
from pydantic import BaseModel, Field

from .base import Tool


class GlobInput(BaseModel):
    """Input schema for Glob tool."""
    pattern: str = Field(description="The glob pattern to match files against")
    path: str = Field(default=".", description="The directory to search in")


class GlobTool(Tool):
    """Find files matching glob patterns."""

    name = "Glob"
    aliases = []
    search_hint = "find files by glob pattern matching"

    def input_schema(self) -> Type[BaseModel]:
        return GlobInput

    async def call(self, args: dict, context: dict) -> dict:
        """Find files matching a glob pattern."""
        pattern = args.get("pattern", "*")
        search_path = args.get("path", ".")

        if not os.path.isabs(search_path):
            search_path = os.path.join(context.get("cwd", os.getcwd()), search_path)

        try:
            if not os.path.exists(search_path):
                return {"data": f"Error: Path not found: {search_path}"}

            results = []
            max_results = 500

            for root, dirs, files in os.walk(search_path):
                # Skip hidden directories and common ignores
                dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("node_modules", "__pycache__", ".git", "venv", ".venv", "dist", "build")]

                # Match files
                for name in files + dirs:
                    if fnmatch.fnmatch(name, pattern):
                        full_path = os.path.join(root, name)
                        rel_path = os.path.relpath(full_path, search_path)
                        results.append(rel_path)

                if len(results) >= max_results:
                    break

            results.sort()

            if len(results) >= max_results:
                results.append(f"... [truncated at {max_results} results]")

            return {
                "data": {
                    "pattern": pattern,
                    "path": search_path,
                    "count": min(len(results), max_results),
                    "results": results[:max_results],
                },
            }
        except Exception as e:
            return {"data": f"Error during glob search: {str(e)}"}

    async def description(self, input_schema: dict, options: dict) -> str:
        return "Find files matching a glob pattern. Use for finding files by name patterns (e.g., '*.py', 'test_*.ts')."

    def is_read_only(self, input_data: dict = None) -> bool:
        return True

    def is_search_or_read_command(self, input_data: dict = None) -> dict:
        return {"is_search": True, "is_read": False, "is_list": False}

    def get_activity_description(self, input_data: dict = None) -> str:
        if not input_data:
            return "Globbing files"
        return f"Globbing {input_data.get('pattern', '')}"
