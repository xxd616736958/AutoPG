"""
Memory system for AutoPG.
Architecturally identical to AutoPG's memory directory system (src/memdir/).
Stores persistent per-project facts that are loaded into the system prompt.
"""
import os
import re
import yaml
from typing import Optional


class MemoryManager:
    """
    Manages the persistent file-based memory system.
    Mirrors AutoPG's memdir/memdir.ts and MEMORY.md mechanics.

    Memory files are stored in ~/.autopg/projects/<project-hash>/memory/
    Each file has YAML frontmatter with name, description, and metadata.
    """

    def __init__(self, project_root: str = None):
        self.project_root = project_root or os.getcwd()
        self.memory_dir = self._get_memory_dir()

    def _get_memory_dir(self) -> str:
        """Get the memory directory path for the current project."""
        # Use a hash of the project path to namespace memories
        import hashlib
        project_hash = hashlib.md5(self.project_root.encode()).hexdigest()[:12]
        base = os.environ.get(
            "AUTOPG_MEMORY_PATH",
            os.path.expanduser("~/.autopg"),
        )
        return os.path.join(base, "projects", project_hash, "memory")

    def _ensure_dir(self):
        """Ensure the memory directory exists."""
        os.makedirs(self.memory_dir, exist_ok=True)

    def get_index_path(self) -> str:
        """Get the path to MEMORY.md index file."""
        return os.path.join(self.memory_dir, "MEMORY.md")

    def read_index(self) -> list[dict]:
        """Read the MEMORY.md index file and return parsed entries."""
        index_path = self.get_index_path()
        if not os.path.exists(index_path):
            return []

        entries = []
        try:
            with open(index_path, "r") as f:
                content = f.read()

            # Parse markdown list entries: "- [Title](file.md) — description"
            pattern = r"- \[([^\]]+)\]\(([^)]+)\)\s*(?:—\s*(.*))?"
            for match in re.finditer(pattern, content):
                entries.append({
                    "title": match.group(1),
                    "file": match.group(2),
                    "description": match.group(3) or "",
                })
        except Exception:
            pass

        return entries

    def read_memory(self, filename: str) -> Optional[dict]:
        """Read a single memory file with frontmatter."""
        filepath = os.path.join(self.memory_dir, filename)
        if not os.path.exists(filepath):
            return None

        try:
            with open(filepath, "r") as f:
                content = f.read()

            # Parse YAML frontmatter
            parts = content.split("---", 2)
            if len(parts) >= 3:
                frontmatter = yaml.safe_load(parts[1]) or {}
                body = parts[2].strip()
                return {
                    "frontmatter": frontmatter,
                    "body": body,
                    "filepath": filepath,
                }
            else:
                return {
                    "frontmatter": {},
                    "body": content.strip(),
                    "filepath": filepath,
                }
        except Exception:
            return None

    def write_memory(self, name: str, description: str, body: str, metadata: dict = None) -> str:
        """Write a new memory file with frontmatter."""
        self._ensure_dir()

        # Create filename from name slug
        filename = re.sub(r"[^a-z0-9-]", "", name.lower().replace(" ", "-")) + ".md"
        filepath = os.path.join(self.memory_dir, filename)

        # Build frontmatter
        meta = metadata or {}
        meta.setdefault("type", "reference")

        frontmatter = yaml.dump({
            "name": name,
            "description": description,
            "metadata": meta,
        }, default_flow_style=False, allow_unicode=True).strip()

        content = f"---\n{frontmatter}\n---\n\n{body}\n"

        with open(filepath, "w") as f:
            f.write(content)

        # Update index
        self._update_index(name, filename, description)

        return filename

    def _update_index(self, title: str, filename: str, description: str):
        """Add or update an entry in MEMORY.md."""
        index_path = self.get_index_path()
        self._ensure_dir()

        entries = self.read_index()
        entry_line = f"- [{title}]({filename}) — {description}"

        # Check if this entry already exists
        updated = False
        new_entries = []
        for entry in entries:
            if entry["file"] == filename:
                new_entries.append(entry_line)
                updated = True
            else:
                new_entries.append(
                    f"- [{entry['title']}]({entry['file']})"
                    + (f" — {entry['description']}" if entry['description'] else "")
                )

        if not updated:
            new_entries.append(entry_line)

        with open(index_path, "w") as f:
            f.write("\n".join(new_entries) + "\n")

    def delete_memory(self, filename: str) -> bool:
        """Delete a memory file and remove from index."""
        filepath = os.path.join(self.memory_dir, filename)
        if not os.path.exists(filepath):
            return False

        os.remove(filepath)

        # Update index
        entries = self.read_index()
        new_entries = [
            f"- [{e['title']}]({e['file']})"
            + (f" — {e['description']}" if e['description'] else "")
            for e in entries
            if e["file"] != filename
        ]

        index_path = self.get_index_path()
        with open(index_path, "w") as f:
            f.write("\n".join(new_entries) + "\n")

        return True

    def list_memories(self) -> list[dict]:
        """List all memories with their metadata."""
        entries = self.read_index()
        result = []
        for entry in entries:
            mem = self.read_memory(entry["file"])
            if mem:
                result.append({
                    "title": entry["title"],
                    "file": entry["file"],
                    "description": entry["description"],
                    "type": mem["frontmatter"].get("metadata", {}).get("type", "unknown"),
                    "body": mem["body"],
                })
        return result

    def get_memory_prompt(self) -> str:
        """Build the memory prompt section for the system prompt."""
        memories = self.list_memories()
        if not memories:
            return ""

        lines = [
            "# Memory",
            "",
            "You have a persistent file-based memory. The following memories exist:",
            "",
        ]
        for mem in memories:
            lines.append(f"- **{mem['title']}**: {mem['description']} (type: {mem['type']})")
        lines.append("")
        lines.append("Use Read to view specific memories. Use Write to create or update memories.")

        return "\n".join(lines)
