"""
FileWrite tool for db-claude.
Architecturally identical to Claude Code's FileWriteTool.
"""
import os
from typing import Type, Any
from pydantic import BaseModel, Field

from .base import Tool, PermissionResult


class FileWriteInput(BaseModel):
    """Input schema for FileWrite tool."""
    file_path: str = Field(description="The absolute path to the file to write (must be absolute)")
    content: str = Field(description="The content to write to the file")


class FileWriteTool(Tool):
    """Write a file to the local filesystem."""

    name = "Write"
    aliases = []
    search_hint = "write a file to disk, overwriting if exists"

    def format_call(self, args: dict) -> str:
        fp = args.get("file_path", "")
        fn = os.path.basename(fp) if fp else "?"
        return f"Write({fn})"

    def format_result(self, data: Any) -> str:
        if isinstance(data, dict):
            size = data.get("size", 0)
            existed = data.get("existed_before", False)
            status = "overwritten" if existed else "written"
            if size > 0:
                return f"{status} ({size:,} bytes)"
            return status
        return str(data)[:120]

    def input_schema(self) -> Type[BaseModel]:
        return FileWriteInput

    async def call(self, args: dict, context: dict) -> dict:
        """Write content to a file."""
        file_path = args.get("file_path", "")
        content = args.get("content", "")

        # Security: ensure absolute path
        if not os.path.isabs(file_path):
            file_path = os.path.join(context.get("cwd", os.getcwd()), file_path)

        try:
            # Create parent directories if needed
            parent_dir = os.path.dirname(file_path)
            if parent_dir and not os.path.exists(parent_dir):
                os.makedirs(parent_dir, exist_ok=True)

            existed = os.path.exists(file_path)

            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)

            file_size = os.path.getsize(file_path)

            return {
                "data": {
                    "status": "written",
                    "file_path": file_path,
                    "size": file_size,
                    "existed_before": existed,
                },
            }
        except Exception as e:
            return {"data": f"Error writing file: {str(e)}"}

    async def description(self, input_schema: dict, options: dict) -> str:
        return "Write a file to the local filesystem, overwriting if one exists. Use when creating a new file or fully replacing one."

    def is_read_only(self, input_data: dict = None) -> bool:
        return False

    def is_destructive(self, input_data: dict = None) -> bool:
        return True  # Overwrites files

    async def check_permissions(self, input_data: dict, context: dict) -> PermissionResult:
        return PermissionResult(behavior="ask", updated_input=input_data)

    def get_activity_description(self, input_data: dict = None) -> str:
        if not input_data:
            return "Writing file"
        path = input_data.get("file_path", "")
        return f"Writing {os.path.basename(path)}"

    def get_path(self, input_data: dict) -> str:
        return input_data.get("file_path", "")

    def to_auto_classifier_input(self, input_data: dict) -> str:
        return f"{input_data.get('file_path', '')}: new content"
