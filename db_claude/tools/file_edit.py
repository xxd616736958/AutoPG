"""
FileEdit tool for db-claude.
Architecturally identical to Claude Code's FileEditTool.
Uses exact string replacement for precise edits.
"""
import os
from typing import Type, Any
from pydantic import BaseModel, Field

from .base import Tool, PermissionResult


class FileEditInput(BaseModel):
    """Input schema for FileEdit tool."""
    file_path: str = Field(description="The absolute path to the file to modify")
    old_string: str = Field(description="The text to replace")
    new_string: str = Field(description="The text to replace it with (must be different from old_string)")
    replace_all: bool = Field(default=False, description="Replace all occurrences of old_string")


class FileEditTool(Tool):
    """Perform exact string replacements in a file."""

    name = "Edit"
    aliases = []
    search_hint = "perform exact string replacement in a file"

    def format_call(self, args: dict) -> str:
        fp = args.get("file_path", "")
        fn = os.path.basename(fp) if fp else "?"
        old = args.get("old_string", "")[:40]
        new = args.get("new_string", "")[:40]
        return f"Edit({fn})"

    def format_result(self, data: Any) -> str:
        if isinstance(data, dict):
            n = data.get("occurrences_replaced", 0)
            total = data.get("total_occurrences", 0)
            if n == 1 and total == 1:
                return "replaced 1 occurrence"
            return f"replaced {n}/{total} occurrences"
        return str(data)[:120]

    def input_schema(self) -> Type[BaseModel]:
        return FileEditInput

    async def call(self, args: dict, context: dict) -> dict:
        """Edit a file by replacing exact string matches."""
        file_path = args.get("file_path", "")
        old_string = args.get("old_string", "")
        new_string = args.get("new_string", "")
        replace_all = args.get("replace_all", False)

        if not os.path.isabs(file_path):
            file_path = os.path.join(context.get("cwd", os.getcwd()), file_path)

        if old_string == new_string:
            return {"data": "Error: old_string and new_string must be different"}

        try:
            if not os.path.exists(file_path):
                return {"data": f"Error: File not found: {file_path}"}

            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            # Find the old_string
            count = content.count(old_string)
            if count == 0:
                return {"data": f"Error: old_string not found in file. It must match exactly including whitespace."}

            if not replace_all and count > 1:
                return {
                    "data": (
                        f"Error: old_string found {count} times in file. "
                        "Set replace_all=true to replace all occurrences, "
                        "or make old_string more specific to match uniquely."
                    ),
                }

            # Perform replacement
            new_content = content.replace(old_string, new_string) if replace_all else content.replace(old_string, new_string, 1)

            with open(file_path, "w", encoding="utf-8") as f:
                f.write(new_content)

            return {
                "data": {
                    "status": "edited",
                    "file_path": file_path,
                    "occurrences_replaced": 1 if not replace_all else count,
                    "total_occurrences": count,
                },
            }
        except Exception as e:
            return {"data": f"Error editing file: {str(e)}"}

    async def description(self, input_schema: dict, options: dict) -> str:
        return "Performs exact string replacement in a file. old_string must match the file exactly including indentation. Use replace_all=true to replace every occurrence."

    def is_read_only(self, input_data: dict = None) -> bool:
        return False

    def is_destructive(self, input_data: dict = None) -> bool:
        return True

    async def check_permissions(self, input_data: dict, context: dict) -> PermissionResult:
        return PermissionResult(behavior="ask", updated_input=input_data)

    def get_activity_description(self, input_data: dict = None) -> str:
        if not input_data:
            return "Editing file"
        path = input_data.get("file_path", "")
        return f"Editing {os.path.basename(path)}"

    def get_path(self, input_data: dict) -> str:
        return input_data.get("file_path", "")

    def to_auto_classifier_input(self, input_data: dict) -> str:
        return f"{input_data.get('file_path', '')}: {input_data.get('old_string', '')[:100]} → {input_data.get('new_string', '')[:100]}"
