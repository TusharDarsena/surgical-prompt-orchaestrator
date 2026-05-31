# SPO Architecture — Surgical Prompt Orchestrator

SPO is a **prompt stitching engine** designed to bridge the gap between academic research (PDFs/NotebookLM) and structural writing (Claude). It maintains the "state" of a thesis that LLMs otherwise lack.

---

## 1. System Overview

SPO is built as a split-architecture application:
- **Backend:** FastAPI (Python) handling data persistence, prompt compilation, and external integrations (NotebookLM/Drive).
- **Frontend (Migrating):** 
    - **Legacy:** Streamlit app (`spo_frontend/app.py`).
    - **Modern:** FastAPI + Jinja2 + HTML/CSS/JS (served directly from the backend via routers in `spo_frontend/new_pages_already_migrated/`).
- **Persistence:** Local JSON file system (flat-file DB) for maximum portability and manual reviewability.

---

## 2. Core Concepts

### The Two-Prompt Workflow
1. **Architect Phase (Claude):** Stitches thesis synopsis + source index cards  into a massive prompt. Claude outputs a `chapterization.json` file that contains the `subtopics`.
2. **Writing Phase (NotebookLM):** Stitches the approved `chapterization.json` + writing rules + context. User pastes this into NotebookLM (grounded in PDFs) to generate the draft.
3. **Consistency Phase:** A summary of the `draft.json` is saved to the "Consistency Chain," which is injected into the next subtopic's prompt to ensure argumentative flow.

---

## 3. Key Workflows

### Surgical Injection (`compiler_service.py`)
The system performs multi-layered injection to create high-context prompts:


### Source Resolution
The system maps local source IDs to Google Drive links using `drive_scan_result.json`. This allows the generated prompts to include direct links for the user to verify citations.

---

## 5. Future Roadmap

- **Book Ingestion Helper:** Automated extraction of index card fields from raw chapter text.
- **Theme Explorer:** Visualizing theme coverage and identifying gaps in the source library.

