"""Edit tool."""
import os, json
from pydantic import BaseModel, Field
from langchain_core.tools import tool

class FileEditInput(BaseModel):
    file_path: str = Field(description="Absolute path to the file to modify")
    old_string: str = Field(description="Exact text to replace")
    new_string: str = Field(description="Replacement text (must differ from old_string)")
    replace_all: bool = Field(default=False)

@tool(args_schema=FileEditInput)
async def edit(file_path: str, old_string: str, new_string: str, replace_all: bool = False) -> str:
    """Perform exact string replacement in a file. old_string must match exactly."""
    fp = file_path
    if not os.path.isabs(fp): fp = os.path.join(os.getcwd(), fp)
    if old_string == new_string: return json.dumps("Error: old_string and new_string must differ")
    try:
        if not os.path.exists(fp): return json.dumps(f"Error: File not found: {fp}")
        with open(fp, "r", encoding="utf-8") as f: content = f.read()
        count = content.count(old_string)
        if count == 0: return json.dumps("Error: old_string not found. Must match exactly including whitespace.")
        if not replace_all and count > 1: return json.dumps(f"Error: old_string found {count} times. Use replace_all=true or make it more specific.")
        new_content = content.replace(old_string, new_string) if replace_all else content.replace(old_string, new_string, 1)
        with open(fp, "w", encoding="utf-8") as f: f.write(new_content)
        return json.dumps({"status": "edited", "file_path": fp, "occurrences_replaced": 1 if not replace_all else count, "total_occurrences": count})
    except Exception as e: return json.dumps(f"Error editing file: {str(e)}")
