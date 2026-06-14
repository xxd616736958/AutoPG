"""Read tool — Claude Code format."""
import os
from typing import Type, Optional, Any
from pydantic import BaseModel, Field
from .base import Tool

class FileReadInput(BaseModel):
    file_path: str = Field(description="The absolute path to the file to read")
    offset: int = Field(default=0, description="The line number to start reading from")
    limit: Optional[int] = Field(default=None, description="The number of lines to read")

class FileReadTool(Tool):
    name = "Read"; aliases = []; search_hint = "read file contents"

    def input_schema(self) -> Type[BaseModel]: return FileReadInput

    def format_call(self, args: dict) -> str:
        """Claude Code: Read(file_path)"""
        fp = args.get("file_path", "")
        fn = os.path.basename(fp) if fp else "?"
        return f"Read({fn})"

    def format_result(self, data: Any) -> str:
        if isinstance(data, str) and "\n" in data:
            lines = data.strip().split("\n")
            line_count = len([l for l in lines if l.strip() and not l.startswith("...")])
            return f"{line_count} lines"
        s = str(data) if not isinstance(data, str) else data
        return s[:120] + ("..." if len(s) > 120 else "")

    async def call(self, args: dict, context: dict) -> dict:
        file_path = args.get("file_path", "")
        if not os.path.isabs(file_path):
            file_path = os.path.join(context.get("cwd", os.getcwd()), file_path)
        try:
            if not os.path.exists(file_path): return {"data": f"Error: File not found: {file_path}"}
            if os.path.isdir(file_path): return {"data": f"Error: Path is a directory: {file_path}"}
            if self._is_binary(file_path): return {"data": f"[Binary file: {os.path.getsize(file_path)} bytes]"}
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            total = len(lines)
            offset = max(args.get("offset", 0), 0)
            limit = args.get("limit")
            if offset > 0: lines = lines[offset - 1:]
            if limit is not None: lines = lines[:limit]
            result_lines = []
            start = offset if offset > 0 else 1
            for i, line in enumerate(lines):
                result_lines.append(f"{start + i}\t{line.rstrip()}")
            if len(result_lines) > 2000:
                result_lines = result_lines[:2000]
                result_lines.append(f"... [truncated, showing first 2000 of {total} lines]")
            return {"data": "\n".join(result_lines)}
        except Exception as e:
            return {"data": f"Error reading file: {str(e)}"}

    def _is_binary(self, file_path: str) -> bool:
        try:
            with open(file_path, "rb") as f: chunk = f.read(1024)
            return b"\x00" in chunk
        except: return True

    async def description(self, input_schema: dict, options: dict) -> str:
        return "Read the contents of a file from the local filesystem."
    def is_read_only(self, input_data: dict = None) -> bool: return True
    def get_activity_description(self, input_data: dict = None) -> str:
        if not input_data: return "Reading file"
        return f"Reading {os.path.basename(input_data.get('file_path', ''))}"
    def is_search_or_read_command(self, input_data: dict = None) -> dict:
        return {"is_search": False, "is_read": True, "is_list": False}
