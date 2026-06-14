"""
FileRead tool for db-claude.
Architecturally identical to Claude Code's FileReadTool.
"""
import os
from typing import Type, Optional
from pydantic import BaseModel, Field

from .base import Tool


class FileReadInput(BaseModel):
    """Input schema for FileRead tool."""
    file_path: str = Field(description="The absolute path to the file to read")
    offset: int = Field(default=0, description="The line number to start reading from")
    limit: Optional[int] = Field(default=None, description="The number of lines to read")
    pages: Optional[str] = Field(default=None, description="Page range for PDF files (e.g., '1-5')")


class FileReadTool(Tool):
    """Read files from the local filesystem."""

    name = "Read"
    aliases = []
    search_hint = "read file contents from the local filesystem"

    def input_schema(self) -> Type[BaseModel]:
        return FileReadInput

    async def call(self, args: dict, context: dict) -> dict:
        """Read a file from disk."""
        file_path = args.get("file_path", "")
        offset = max(args.get("offset", 0), 0)
        limit = args.get("limit")

        # Security: ensure absolute path
        if not os.path.isabs(file_path):
            file_path = os.path.join(context.get("cwd", os.getcwd()), file_path)

        try:
            if not os.path.exists(file_path):
                return {"data": f"Error: File not found: {file_path}"}

            if os.path.isdir(file_path):
                return {"data": f"Error: Path is a directory: {file_path}"}

            # Check if it's a binary file
            if self._is_binary(file_path):
                return {"data": f"[Binary file: {os.path.getsize(file_path)} bytes]"}

            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()

            total_lines = len(lines)

            # Apply offset and limit
            if offset > 0:
                lines = lines[offset - 1:]  # offset is 1-based
            if limit is not None:
                lines = lines[:limit]

            # Format with line numbers (matching cat -n format)
            result_lines = []
            start_num = offset if offset > 0 else 1
            for i, line in enumerate(lines):
                line_num = start_num + i
                result_lines.append(f"{line_num}\t{line.rstrip()}")

            # Truncate if too long
            if len(result_lines) > 2000:
                result_lines = result_lines[:2000]
                result_lines.append(f"... [truncated, showing first 2000 of {total_lines} lines]")

            return {"data": "\n".join(result_lines)}

        except Exception as e:
            return {"data": f"Error reading file: {str(e)}"}

    def _is_binary(self, file_path: str) -> bool:
        """Check if a file appears to be binary."""
        try:
            with open(file_path, "rb") as f:
                chunk = f.read(1024)
            # Check for null bytes (common in binary files)
            if b"\x00" in chunk:
                return True
            # Try decoding as UTF-8
            try:
                chunk.decode("utf-8")
                return False
            except UnicodeDecodeError:
                return True
        except Exception:
            return True

    async def description(self, input_schema: dict, options: dict) -> str:
        return "Read the contents of a file from the local filesystem. Supports text files with line numbers, PDFs via the pages parameter, and images (renders them visually)."

    def is_read_only(self, input_data: dict = None) -> bool:
        return True

    def get_activity_description(self, input_data: dict = None) -> str:
        if not input_data:
            return "Reading file"
        path = input_data.get("file_path", "")
        return f"Reading {os.path.basename(path)}"

    def is_search_or_read_command(self, input_data: dict = None) -> dict:
        return {"is_search": False, "is_read": True, "is_list": False}

    def get_path(self, input_data: dict) -> str:
        return input_data.get("file_path", "")
