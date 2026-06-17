"""Glob tool."""
import os, fnmatch, json
from pydantic import BaseModel, Field
from langchain_core.tools import tool

class GlobInput(BaseModel):
    pattern: str = Field(description="Glob pattern to match files against (e.g., '*.py', 'test_*.ts')")
    path: str = Field(default=".", description="Directory to search in")

@tool(args_schema=GlobInput)
async def glob(pattern: str, path: str = ".") -> str:
    """Find files matching a glob pattern. Use instead of Bash 'find' or 'ls'."""
    sp = os.path.expanduser(path)
    if not os.path.isabs(sp): sp = os.path.join(os.getcwd(), sp)
    try:
        if not os.path.exists(sp): return json.dumps(f"Error: Path not found: {sp}")
        results = []
        for root, dirs, files in os.walk(sp):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("node_modules","__pycache__",".git","venv",".venv","dist","build")]
            for name in files + dirs:
                if fnmatch.fnmatch(name, pattern):
                    results.append(os.path.relpath(os.path.join(root, name), sp))
                if len(results) >= 500: break
            if len(results) >= 500: break
        results.sort()
        return json.dumps({"pattern": pattern, "path": sp, "count": len(results), "results": results[:500]})
    except Exception as e: return json.dumps(f"Error during glob: {str(e)}")
