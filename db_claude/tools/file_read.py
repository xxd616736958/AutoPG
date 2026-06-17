"""Read tool."""
import os, json
from pydantic import BaseModel, Field
from langchain_core.tools import tool

class FileReadInput(BaseModel):
    file_path: str = Field(description="Absolute path to the file to read")
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=None)

@tool(args_schema=FileReadInput)
async def read(file_path: str, offset: int = 0, limit: int = None) -> str:
    """Read file contents from the local filesystem. Returns text with line numbers."""
    fp = os.path.expanduser(file_path)
    if not os.path.isabs(fp): fp = os.path.join(os.getcwd(), fp)
    try:
        if not os.path.exists(fp): return json.dumps(f"Error: File not found: {fp}")
        if os.path.isdir(fp): return json.dumps(f"Error: Path is a directory: {fp}")
        with open(fp,"rb") as bf:
            if b"\x00" in bf.read(1024): return json.dumps(f"[Binary file: {os.path.getsize(fp)} bytes]")
        with open(fp,"r",encoding="utf-8",errors="replace") as f: lines=f.readlines()
        total=len(lines)
        if offset>0: lines=lines[offset-1:]
        if limit is not None: lines=lines[:limit]
        start=offset if offset>0 else 1
        result=[f"{start+i}\t{l.rstrip()}" for i,l in enumerate(lines)]
        if len(result)>2000: result=result[:2000]+[f"... [truncated, first 2000 of {total} lines]"]
        return "\n".join(result)
    except Exception as e: return json.dumps(f"Error reading file: {str(e)}")
