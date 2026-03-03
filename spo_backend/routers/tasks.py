"""
Task Blueprint Router
---------------------
Stores the approved Task.md blueprint for each subtopic.

Workflow position:
  1. Compile Architect Mega-Prompt  →  POST /compile/architect-prompt/...
  2. Paste into Claude, get Task.md
  3. Edit Task.md in your editor
  4. Save approved Task.md here    →  POST /tasks/{chapter_id}/{subtopic_id}
  5. Compile NotebookLM prompt     →  GET  /compile/notebooklm-prompt/...
     (reads from here automatically)

The Task.md is stored as both raw markdown text AND parsed sections,
so the NotebookLM compiler can read the structured parts directly.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from services import storage

router = APIRouter(prefix="/tasks", tags=["Task Blueprints"])


class TaskBlueprintSaveRequest(BaseModel):
    raw_markdown: str = Field(
        ...,
        description=(
            "The full Task.md text exactly as approved. "
            "Paste the markdown Claude output, after your edits."
        )
    )
    # Parsed fields — fill these if you want the NotebookLM compiler
    # to use structured data. If left empty, it uses raw_markdown as a block.
    core_objective: Optional[str] = Field(
        None,
        description="The 'Core Objective' section from Task.md. One sentence."
    )
    focus_points: list[str] = Field(
        default_factory=list,
        description="The bullet points from the 'Focus Points' section."
    )
    key_terms: list[str] = Field(
        default_factory=list,
        description="Terms from the 'Key Terms to Use' section."
    )
    do_not_include: list[str] = Field(
        default_factory=list,
        description="Items from the 'Do Not Include' section."
    )
    word_count_target: Optional[int] = Field(
        None,
        description="Target word count for this section. e.g. 800"
    )


@router.post(
    "/{chapter_id}/{subtopic_id}",
    summary="Save approved Task.md blueprint for a subtopic"
)
def save_task_blueprint(
    chapter_id: str,
    subtopic_id: str,
    req: TaskBlueprintSaveRequest
):
    """
    Save the Task.md after you've reviewed and edited it.
    This is the gate between the Architect phase and the NotebookLM phase.
    """
    # Verify the subtopic exists
    chapter = storage.read_chapter(chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail=f"Chapter '{chapter_id}' not found.")
    subtopics = chapter.get("subtopics", [])
    subtopic = next((s for s in subtopics if s["subtopic_id"] == subtopic_id), None)
    if not subtopic:
        raise HTTPException(status_code=404, detail=f"Subtopic '{subtopic_id}' not found.")

    data = req.model_dump()
    data["chapter_id"] = chapter_id
    data["subtopic_id"] = subtopic_id
    data["subtopic_number"] = subtopic.get("number", "")
    data["subtopic_title"] = subtopic.get("title", "")
    data["approved"] = True
    data["created_at"] = datetime.utcnow().isoformat()

    return storage.write_task_blueprint(chapter_id, subtopic_id, data)


@router.get(
    "/{chapter_id}/{subtopic_id}",
    summary="Get the approved Task.md for a subtopic"
)
def get_task_blueprint(chapter_id: str, subtopic_id: str):
    data = storage.read_task_blueprint(chapter_id, subtopic_id)
    if not data:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No approved Task.md found for subtopic '{subtopic_id}'. "
                "Complete the Architect phase first: "
                "GET /compile/architect-prompt/{chapter_id}/{subtopic_id}, "
                "paste into Claude, edit, then save here."
            )
        )
    return data


@router.get("/", summary="List all saved Task.md blueprints")
def list_task_blueprints():
    blueprints = storage.list_task_blueprints()
    return {
        "blueprints": blueprints,
        "count": len(blueprints)
    }


@router.delete(
    "/{chapter_id}/{subtopic_id}",
    summary="Delete a Task.md (to regenerate from scratch)"
)
def delete_task_blueprint(chapter_id: str, subtopic_id: str):
    if not storage.delete_task_blueprint(chapter_id, subtopic_id):
        raise HTTPException(status_code=404, detail="Task blueprint not found.")
    return {"deleted": f"{chapter_id}/{subtopic_id}"}