"""Write tool."""
import os, json
from pydantic import BaseModel, Field
from langchain_core.tools import tool

class FileWriteInput(BaseModel):
    file_path: str = Field(description="Absolute path to write to (must be absolute)")
    content: str = Field(description="Content to write")

@tool(args_schema=FileWriteInput)
async def write(file_path: str, content: str) -> str:
    """Write a file to disk, overwriting if exists. Creates parent directories as needed."""
    fp = file_path
    if not os.path.isabs(fp): fp = os.path.join(os.getcwd(), fp)
    try:
        os.makedirs(os.path.dirname(fp) or ".", exist_ok=True)
        existed = os.path.exists(fp)
        with open(fp, "w", encoding="utf-8") as f: f.write(content)
        return json.dumps({"status": "written", "file_path": fp, "size": os.path.getsize(fp), "existed_before": existed})
    except Exception as e: return json.dumps(f"Error writing file: {str(e)}")
