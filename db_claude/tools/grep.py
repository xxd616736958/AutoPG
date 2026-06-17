"""Grep tool."""
import os, re, subprocess, json
from pydantic import Field
from langchain_core.tools import tool

@tool
async def grep(
    pattern: str = Field(description="Regular expression pattern to search for"),
    path: str = Field(default=".", description="Directory or file to search in"),
    include: str = Field(default="", description="File pattern to include (e.g., '*.py')"),
    ignore_case: bool = Field(default=False, description="Case-insensitive search"),
    max_results: int = Field(default=100, ge=1, le=500, description="Maximum number of results to return"),
) -> str:
    """Search file contents using regular expressions. Prefer over Bash 'grep'.

    Args:
        pattern: Regular expression pattern
        path: Directory or file to search in
        include: File pattern to include
        ignore_case: Case-insensitive search
        max_results: Maximum number of results
    """
    sp = os.path.expanduser(path)
    if not os.path.isabs(sp): sp = os.path.join(os.getcwd(), sp)
    try:
        if not os.path.exists(sp): return json.dumps(f"Error: Path not found: {sp}")
        try:
            cmd = ["grep","-rn","--color=never","-m",str(max_results)]
            if ignore_case: cmd.append("-i")
            if include: cmd.extend(["--include", include])
            cmd.extend([pattern, sp])
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if r.returncode in (0,1):
                lines = [l for l in r.stdout.strip().split("\n") if l]
                return json.dumps({"pattern": pattern, "path": sp, "count": len(lines), "results": lines[:max_results]})
        except (FileNotFoundError, subprocess.TimeoutExpired): pass
        flags = re.IGNORECASE if ignore_case else 0
        regex = re.compile(pattern, flags)
        results = []
        files = [sp] if os.path.isfile(sp) else []
        if not files:
            for root, dirs, fnames in os.walk(sp):
                dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("node_modules","__pycache__",".git","venv",".venv","dist","build")]
                for fn in fnames:
                    if include and not any(fn.endswith(inc.strip("*")) for inc in include.split(",")): continue
                    files.append(os.path.join(root, fn))
        for fp in files:
            if len(results) >= max_results: break
            try:
                with open(fp,"rb") as bf:
                    if b"\x00" in bf.read(1024): continue
                with open(fp,"r",encoding="utf-8",errors="replace") as f:
                    for i, line in enumerate(f, 1):
                        if regex.search(line):
                            results.append(f"{os.path.relpath(fp,sp)}:{i}:{line.rstrip()}")
                            if len(results) >= max_results: break
            except: continue
        return json.dumps({"pattern": pattern, "path": sp, "count": len(results), "results": results[:max_results]})
    except re.error as e: return json.dumps(f"Invalid regex: {str(e)}")
    except Exception as e: return json.dumps(f"Error during grep: {str(e)}")
