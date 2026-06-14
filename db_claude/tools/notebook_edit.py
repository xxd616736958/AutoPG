"""
NotebookEdit tool for db-claude.
Architecturally identical to Claude Code's NotebookEditTool.
"""
import json
import os
from typing import Type, Optional
from pydantic import BaseModel, Field

from .base import Tool


class NotebookEditInput(BaseModel):
    """Input schema for NotebookEdit tool."""
    notebook_path: str = Field(description="The absolute path to the Jupyter notebook file to edit")
    new_source: str = Field(description="The new source for the cell")
    cell_id: Optional[str] = Field(default=None, description="The ID of the cell to edit")
    cell_type: Optional[str] = Field(default=None, description="The type of the cell: code or markdown")
    edit_mode: str = Field(default="replace", description="The type of edit: replace, insert, or delete")


class NotebookEditTool(Tool):
    """Edit Jupyter notebook cells."""

    name = "NotebookEdit"
    aliases = []
    search_hint = "edit cells in jupyter notebooks"

    def input_schema(self) -> Type[BaseModel]:
        return NotebookEditInput

    async def call(self, args: dict, context: dict) -> dict:
        notebook_path = args.get("notebook_path", "")
        new_source = args.get("new_source", "")
        cell_id = args.get("cell_id")
        cell_type = args.get("cell_type", "code")
        edit_mode = args.get("edit_mode", "replace")

        if not os.path.isabs(notebook_path):
            notebook_path = os.path.join(context.get("cwd", os.getcwd()), notebook_path)

        try:
            if not os.path.exists(notebook_path):
                return {"data": f"Error: Notebook not found: {notebook_path}"}

            with open(notebook_path, "r", encoding="utf-8") as f:
                nb = json.load(f)

            cells = nb.get("cells", [])

            if edit_mode == "replace":
                if not cell_id:
                    return {"data": "Error: cell_id required for replace mode"}
                found = False
                for cell in cells:
                    if cell.get("id") == cell_id:
                        cell["source"] = new_source.split("\n") if isinstance(new_source, str) else new_source
                        if cell_type:
                            cell["cell_type"] = cell_type
                        found = True
                        break
                if not found:
                    return {"data": f"Error: Cell not found: {cell_id}"}

            elif edit_mode == "insert":
                new_cell = {
                    "id": cell_id or f"cell_{len(cells)}",
                    "cell_type": cell_type or "code",
                    "source": new_source.split("\n") if isinstance(new_source, str) else new_source,
                    "metadata": {},
                    "outputs": [],
                    "execution_count": None,
                }
                if cell_id:
                    # Insert after the specified cell
                    insert_idx = next((i for i, c in enumerate(cells) if c.get("id") == cell_id), -1)
                    if insert_idx >= 0:
                        cells.insert(insert_idx + 1, new_cell)
                    else:
                        cells.append(new_cell)
                else:
                    cells.insert(0, new_cell)  # Insert at beginning

            elif edit_mode == "delete":
                if not cell_id:
                    return {"data": "Error: cell_id required for delete mode"}
                nb["cells"] = [c for c in cells if c.get("id") != cell_id]

            else:
                return {"data": f"Error: Unknown edit_mode: {edit_mode}"}

            with open(notebook_path, "w", encoding="utf-8") as f:
                json.dump(nb, f, indent=1, ensure_ascii=False)

            return {
                "data": {
                    "status": "edited",
                    "notebook_path": notebook_path,
                    "edit_mode": edit_mode,
                    "cell_count": len(nb.get("cells", [])),
                },
            }
        except Exception as e:
            return {"data": f"Error editing notebook: {str(e)}"}

    async def description(self, input_schema: dict, options: dict) -> str:
        return "Edit cells in a Jupyter notebook (.ipynb file). Supports replace, insert, and delete modes."

    def is_read_only(self, input_data: dict = None) -> bool:
        return False

    def get_activity_description(self, input_data: dict = None) -> str:
        if not input_data:
            return "Editing notebook"
        return f"Editing {os.path.basename(input_data.get('notebook_path', ''))}"
