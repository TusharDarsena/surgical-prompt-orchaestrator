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
1. **Architect Phase (Claude):** Stitches thesis synopsis + chapter arc + source index cards + previous context into a massive prompt. Claude outputs a `Task.md` (structural blueprint).
2. **Writing Phase (NotebookLM):** Stitches the approved `Task.md` + writing rules + context. User pastes this into NotebookLM (grounded in PDFs) to generate the draft.
3. **Consistency Phase:** A summary of the draft is saved to the "Consistency Chain," which is injected into the next subtopic's prompt to ensure argumentative flow.

---

## 3. Technology Stack

- **Language:** Python 3.10+
- **API Framework:** FastAPI
- **Frontend:** Jinja2 Templates, HTML5, Vanilla CSS, Javascript
- **Data Serialization:** Pydantic (Models), JSON (Persistence)
- **Concurrency:** Windows-compatible `WindowsSelectorEventLoopPolicy`.

---

## 4. Directory Structure

```text
surgical-prompt-orchestrator/
├── spo_backend/                # Core Logic & API
│   ├── models/                 # Pydantic data schemas
│   ├── routers/                # API endpoints (Thesis, Sources, Compiler, etc.)
│   ├── services/               # Business logic
│   │   ├── storage.py          # Flat-file JSON DB manager + In-memory Caching
│   │   ├── compiler_service.py # Claude prompt engine
│   │   ├── source_resolver.py  # Local/Drive file mapping
│   │   └── notebooklm_service.py # NotebookLM integration
│   └── main.py                 # FastAPI entry point & Router registration
├── spo_frontend/               # Frontend Assets & Pages
│   ├── templates/              # HTML templates (Jinja2)
│   ├── static/                 # CSS, JS, and Images
│   └── new_pages_already_migrated/ # Modern FastAPI-based UI
└── spo_data/                   # User data (Thesis, Sources, Tasks, Chain)
```

---

## 5. Data Model & Persistence

Data is stored in `SPO_DATA_DIR` (defaults to `~/spo_data`). The storage layer (`storage.py`) uses a fine-grained **in-memory cache** to minimize disk I/O.

| Component | Storage Path | Description |
| :--- | :--- | :--- |
| **Thesis** | `thesis_context/` | Synopsis (`synopsis.json`) and Chapter structures. |
| **Sources** | `source_groups/` | Metadata and "Index Cards" (structured summaries). |
| **Tasks** | `task_blueprints/` | Approved `Task.md` structures for each subtopic. |
| **Chain** | `consistency_chain/` | Running log of argumentative points to maintain flow. |
| **Notes** | `notes/` | Free-text scratchpad for thesis, sources, and chapters. |
| **Misc** | `misc/` | Internal state like `drive_scan_result.json` and batch progress. |

---

## 6. Key Workflows

### Surgical Injection (`compiler_service.py`)
The system performs multi-layered injection to create high-context prompts:
1. **Thesis Layer:** Research question, objectives, methodology.
2. **Chapter Layer:** The "Chapter Arc" (description of the chapter's argumentative map).
3. **Subtopic Layer:** Specific goals for the current section.
4. **Evidence Layer:** Filtered index cards for relevant sources.
5. **Context Layer:** Summary of the previous section's argument.

### Source Resolution
The system maps local source IDs to Google Drive links using `drive_scan_result.json`. This allows the generated prompts to include direct links for the user to verify citations.

---

## 7. Development Patterns

- **Flat-File First:** Persistence must remain human-readable JSON.
- **Cache Invalidation:** The `storage.py` service handles per-group cache eviction to ensure data consistency in single-user sessions.
- **Purity:** Routers handle HTTP/Templates; Services handle logic/IO.
- **Migration Path:** All new features must be implemented in the FastAPI/Jinja2 stack, eventually phasing out the Streamlit frontend.

---

## 8. Design Evolution (v0.4.0 → v0.5.0)

### From Forms to JSON Imports
The legacy system used individual POST forms for Thesis Synopsis, Chapters, and Sources. This proved too slow for academic workflows.
- **Why:** A 6-field form cannot express a complex synopsis. Users now prepare a rich `thesis.json` or `chapterization.json` (often with LLM assistance) and import it in one shot.
- **Chapter Arc:** Introduced the `chapter_arc` field. Without this "map," Claude would generate generic tasks. The arc constrains the LLM to a specific argumentative role.

### Improved Source Ingestion
The old flow required manual entry for every index card. The new flow encourages extracting structured `source.json` files via NotebookLM (grounded in PDFs) and importing them. This ensures high-quality, evidence-backed index cards.

### Prompt Structure Refinement
The Architect prompt was expanded from 4 to 6 sections, specifically adding the **Chapter Arc** between the Thesis Context and Current Subtopic. This prevents "argumentative drift."

---

## 9. Future Roadmap

- **Book Ingestion Helper:** Automated extraction of index card fields from raw chapter text.
- **Theme Explorer:** Visualizing theme coverage and identifying gaps in the source library.
- **Full Export:** Compiling full chapter context (Synopsis + Arc + Tasks + Consistency Chain) into a single master document.
