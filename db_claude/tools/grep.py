"""
Grep tool for db-claude.
Architecturally identical to Claude Code's GrepTool.
"""
import os
import re
import subprocess
from typing import Type, Any
from pydantic import BaseModel, Field

from .base import Tool


class GrepInput(BaseModel):
    """Input schema for Grep tool."""
    pattern: str = Field(description="The regular expression pattern to search for")
    path: str = Field(default=".", description="The directory or file to search in")
    include: str = Field(default="", description="File pattern to include (e.g., '*.py')")
    exclude: str = Field(default="", description="File pattern to exclude")
    ignore_case: bool = Field(default=False, description="Case-insensitive search")
    max_results: int = Field(default=100, description="Maximum number of results")


class GrepTool(Tool):
    """Search file contents using regex patterns."""

    name = "Grep"
    aliases = []
    search_hint = "search file contents with regular expressions"

    def input_schema(self) -> Type[BaseModel]:
        return GrepInput

    def format_call(self, args: dict) -> str:
        pattern = args.get("pattern", "")
        return f"Grep({pattern[:60]})"

    def format_result(self, data: Any) -> str:
        if isinstance(data, dict):
            count = data.get("count", 0)
            results = data.get("results", [])[:3]
            preview = "; ".join(r[:60] for r in results)
            more = f" ... +{count - 3} more" if count > 3 else ""
            return f"{count} matches" + (f": {preview}{more}" if preview else "")
        return str(data)[:120]

    async def call(self, args: dict, context: dict) -> dict:
        """Search file contents using regex."""
        pattern = args.get("pattern", "")
        search_path = args.get("path", ".")
        include = args.get("include", "")
        exclude = args.get("exclude", "")
        ignore_case = args.get("ignore_case", False)
        max_results = min(args.get("max_results", 100), 500)

        if not os.path.isabs(search_path):
            search_path = os.path.join(context.get("cwd", os.getcwd()), search_path)

        try:
            if not os.path.exists(search_path):
                return {"data": f"Error: Path not found: {search_path}"}

            # Try to use system grep first for speed
            try:
                cmd = ["grep", "-rn", "--color=never"]
                if ignore_case:
                    cmd.append("-i")
                if include:
                    cmd.extend(["--include", include])
                if exclude:
                    cmd.extend(["--exclude", exclude])
                cmd.extend(["-m", str(max_results), pattern, search_path])

                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )

                if result.returncode in (0, 1):
                    lines = result.stdout.strip().split("\n")
                    lines = [l for l in lines if l]  # Filter empty lines
                    return {
                        "data": {
                            "pattern": pattern,
                            "path": search_path,
                            "count": len(lines),
                            "results": lines[:max_results],
                        },
                    }
                # grep returns 2 for errors
            except (FileNotFoundError, subprocess.TimeoutExpired):
                pass  # Fall through to Python implementation

            # Python fallback
            results = []
            flags = re.IGNORECASE if ignore_case else 0

            try:
                regex = re.compile(pattern, flags)
            except re.error as e:
                return {"data": f"Invalid regex pattern: {str(e)}"}

            # Determine if search_path is a file or directory
            if os.path.isfile(search_path):
                files_to_search = [search_path]
            else:
                files_to_search = []
                for root, dirs, files in os.walk(search_path):
                    dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("node_modules", "__pycache__", ".git", "venv", ".venv", "dist", "build")]
                    for fname in files:
                        # Apply include/exclude patterns
                        if include and not any(fname.endswith(inc.strip("*")) for inc in include.split(",")):
                            continue
                        if exclude and any(fname.endswith(exc.strip("*")) for exc in exclude.split(",")):
                            continue
                        files_to_search.append(os.path.join(root, fname))

            for fpath in files_to_search:
                if len(results) >= max_results:
                    break
                try:
                    # Skip binary files
                    if self._is_binary(fpath):
                        continue
                    with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                        for line_num, line in enumerate(f, 1):
                            if regex.search(line):
                                rel_path = os.path.relpath(fpath, search_path)
                                results.append(f"{rel_path}:{line_num}:{line.rstrip()}")
                                if len(results) >= max_results:
                                    break
                except Exception:
                    continue

            return {
                "data": {
                    "pattern": pattern,
                    "path": search_path,
                    "count": len(results),
                    "results": results[:max_results],
                },
            }
        except Exception as e:
            return {"data": f"Error during grep search: {str(e)}"}

    def _is_binary(self, file_path: str) -> bool:
        """Check if a file appears to be binary."""
        try:
            with open(file_path, "rb") as f:
                chunk = f.read(1024)
            return b"\x00" in chunk
        except Exception:
            return True

    async def description(self, input_schema: dict, options: dict) -> str:
        return "Search file contents using regular expression patterns. Returns file paths, line numbers, and matching lines. Use for finding code patterns, usages, or text across files."

    def is_read_only(self, input_data: dict = None) -> bool:
        return True

    def is_search_or_read_command(self, input_data: dict = None) -> dict:
        return {"is_search": True, "is_read": False, "is_list": False}

    def get_activity_description(self, input_data: dict = None) -> str:
        if not input_data:
            return "Searching files"
        return f"Searching for '{input_data.get('pattern', '')}'"
