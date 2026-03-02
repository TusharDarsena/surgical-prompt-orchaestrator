# Quick Test Workflow

## 1. Start the Backend

```bash
cd spo_backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

Open: **http://localhost:8000/docs**

---

## 2. Quick Test Flow (Follow the steps in SETUP.md)

The complete test workflow is in **SETUP.md** with all the exact JSON payloads.

Here's the minimal flow to test "selecting a PDF and creating a mega-prompt":

### A. Setup Your Thesis Structure
1. `POST /thesis/synopsis` - Create your thesis
2. `POST /thesis/chapters` - Add Chapter 1
3. `POST /thesis/chapters/chapter_01/subtopics` - Add subtopic 1.3.2

### B. Add a Source (Your PDF)
4. `POST /sources/groups` - Register a source group (e.g., "Sharma 2003 Thesis")
5. `POST /notes/source_group/{group_id}` - Paste quick reading notes
6. `POST /sources/groups/{group_id}/sources` - Add specific chapter (your PDF)
7. `POST /notes/source/{source_id}` - Paste detailed chapter notes
8. `POST /sources/groups/{group_id}/sources/{source_id}/index-card` - Create the index card

### C. Get Ready-to-Use Prompts
9. `GET /thesis/chapters/chapter_01/subtopics/1_3_2/suggested-sources` - See which sources match
10. **[TODO]** `GET /prompts/architect/chapter_01/1_3_2` - Get the compiled mega-prompt

---

## Missing Piece: Prompt Compiler

The backend currently stores all the data but doesn't yet have an endpoint to **compile the final mega-prompt**.

You need to add:

```python
# routers/prompts.py (NEW FILE)
@router.get("/prompts/architect/{chapter_id}/{subtopic_id}")
def compile_architect_prompt(chapter_id: str, subtopic_id: str):
    # 1. Get synopsis
    # 2. Get chapter
    # 3. Get subtopic
    # 4. Get suggested sources with index cards
    # 5. Get previous section summary
    # 6. Stitch everything into formatted text
    return {"prompt": "...formatted text..."}
```

This will give you copy-paste-ready text to feed into Claude.

---

## Data Location

All data saves to: `~/spo_data/` (or `%USERPROFILE%\spo_data\` on Windows)

You can override with: `SPO_DATA_DIR=/custom/path uvicorn main:app --reload`
