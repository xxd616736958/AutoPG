"""Format utilities for Claude Code-style tool output. Applied to all tools via monkey-patch."""
import os
from typing import Any

# Applied to tools that don't have custom format methods yet

def _patch_tool(tool, format_call_fn, format_result_fn):
    """Add format methods to a tool instance if not already present."""
    if not hasattr(tool, 'format_call') or tool.format_call.__name__ == 'format_call':
        tool.format_call = format_call_fn.__get__(tool, type(tool))
    if not hasattr(tool, 'format_result') or tool.format_result.__name__ == 'format_result':
        tool.format_result = format_result_fn.__get__(tool, type(tool))


def apply_claude_formats(tools_registry):
    """Ensure ALL tools have Claude Code-style format methods.
    This patches tools that were missed in individual updates.
    """
    for tool in tools_registry.all():
        if not hasattr(tool, 'format_call') or 'format_call' not in type(tool).__dict__:
            # Default call format: ToolName(key args)
            def make_format_call(name):
                def _fmt(self, args):
                    # Extract first meaningful arg for display
                    if 'file_path' in args:
                        fn = os.path.basename(str(args['file_path']))
                        return f"{name}({fn})"
                    if 'notebook_path' in args:
                        fn = os.path.basename(str(args['notebook_path']))
                        return f"{name}({fn})"
                    if 'command' in args:
                        cmd = str(args['command'])[:60]
                        return f"{name}({cmd})"
                    if 'pattern' in args:
                        return f"{name}({args['pattern']})"
                    if 'query' in args:
                        return f"{name}({str(args['query'])[:60]})"
                    if 'url' in args:
                        return f"{name}({str(args['url'])[:60]})"
                    if 'subject' in args:
                        return f"{name}({args['subject']})"
                    if 'task_id' in args:
                        return f"{name}({args['task_id']})"
                    return name
                return _fmt
            tool.format_call = make_format_call(tool.name).__get__(tool, type(tool))

        if not hasattr(tool, 'format_result') or 'format_result' not in type(tool).__dict__:
            def _fmt(self, data):
                if isinstance(data, dict):
                    if 'status' in data: return str(data['status'])
                    if 'count' in data: return f"{data['count']} results"
                    if 'id' in data: return f"id: {data['id']}"
                    s = str(data)
                    return s[:120] + ("..." if len(s) > 120 else "")
                s = str(data)
                return s[:120] + ("..." if len(s) > 120 else "")
            tool.format_result = _fmt.__get__(tool, type(tool))
