"""Notebook tool."""
import os, json
from pydantic import Field
from langchain_core.tools import tool

@tool
async def notebook_edit(
    notebook_path: str = Field(description="Absolute path to the Jupyter notebook file to edit"),
    new_source: str = Field(description="The new source for the cell"),
    cell_id: str = Field(default=None, description="The ID of the cell to edit (required for replace/delete)"),
    cell_type: str = Field(default="code", description="Cell type: code or markdown"),
    edit_mode: str = Field(default="replace", description="Edit mode: replace, insert, or delete"),
) -> str:
    """Edit cells in a Jupyter notebook (.ipynb file)."""
    fp = notebook_path
    if not os.path.isabs(fp): fp = os.path.join(os.getcwd(), fp)
    try:
        if not os.path.exists(fp): return json.dumps(f"Error: Notebook not found: {fp}")
        with open(fp) as f: nb = json.load(f)
        cells = nb.get("cells",[])
        if edit_mode == "replace":
            for c in cells:
                if c.get("id")==cell_id: c["source"]=new_source.split("\n"); break
        elif edit_mode == "insert":
            nc = {"id":cell_id or f"cell_{len(cells)}","cell_type":cell_type,"source":new_source.split("\n"),"metadata":{},"outputs":[],"execution_count":None}
            if cell_id:
                idx = next((i for i,c in enumerate(cells) if c.get("id")==cell_id), -1)
                cells.insert(idx+1 if idx>=0 else len(cells), nc)
            else: cells.insert(0, nc)
        elif edit_mode == "delete":
            nb["cells"] = [c for c in cells if c.get("id")!=cell_id]
        with open(fp,"w") as f: json.dump(nb,f,indent=1,ensure_ascii=False)
        return json.dumps({"status":"edited","notebook_path":fp,"edit_mode":edit_mode,"cell_count":len(nb.get("cells",[]))})
    except Exception as e: return json.dumps(f"Error editing notebook: {str(e)}")
