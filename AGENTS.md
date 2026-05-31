# AGENTS.md — Project Intelligence File

SPO automates NotebookLM to draft PhD dissertation sections from uploaded academic sources, using a two-stage pipeline (NotebookLM → Gemini expansion).

---

## Stack

| Layer | Technology |
|---|---|
| **Backend API** | Python FastAPI + Uvicorn |
| **Frontend (Modern)** | Jinja2 Templates + Vanilla CSS + Vanilla JS |
| **Frontend (Legacy)** | Streamlit (`spo_frontend/app.py`) |
| **Data Layer** | Flat-file JSON (no database, no ORM) |
| **Validation** | Pydantic v2 models |
| **Async** | Windows-compatible `WindowsSelectorEventLoopPolicy` |
| **External APIs** | Google Drive API, Google Docs API, notebooklm-py |
| **Styling** | Vanilla CSS (`spo_global.css` + per-page files) |
| **Package mgr** | pip (`spo_backend/requirements.txt`) |
| **Run** | `uvicorn spo_backend.main:app --reload --port 8000` (always from project root) |

**Backend deps:** `fastapi`, `uvicorn[standard]`, `pydantic`, `python-dotenv`, `notebooklm-py[browser]`, `playwright`, `httpx`

---

## Folder Structure

```
/
├── spo_backend/                    # Core Logic & API (FastAPI)
│   ├── models/                     # Pydantic data schemas
│   │   ├── thesis.py
│   │   ├── sources.py
│   │   ├── notes.py
│   │   └── consistency.py
│   ├── routers/                    # API endpoints (one file per resource)
│   │   ├── thesis.py               # /thesis/* — synopsis, chapters, subtopics, namespaces
│   │   ├── sources.py              # /sources/* — groups, sources, index cards, library-view
│   │   ├── compiler.py             # /compile/* — prompt compilation
│   │   ├── importer.py             # /import/* — bulk JSON imports
│   │   ├── drive.py                # /drive/* — local scan, Drive link registry
│   │   ├── sections.py             # /sections/* — draft read/write/delete
│   │   ├── consistency.py          # /consistency/* — consistency chain
│   │   ├── notes.py                # /notes/* — scratchpad notes
│   │   ├── notebooklm.py           # /notebooklm/* — automation, batch, summarize
│   │   ├── gdocs.py                # /gdocs/* — Google Docs export
│   │   ├── source_indexer.py       # /source-index/* — source card indexing pipeline
│   │   └── __init__.py
│   ├── services/                   # Business logic (no HTTP, no templates)
│   │   ├── storage.py              # Flat-file JSON DB + 3 in-memory caches
│   │   ├── compiler_service.py     # Prompt stitching engine
│   │   ├── source_resolver.py      # Local/Drive file mapping + source ID resolution
│   │   ├── notebooklm_service.py   # NotebookLM automation (notebooklm-py)
│   │   ├── google_docs_service.py  # Google Docs API integration
│   │   ├── source_importer.py      # source.json bulk import logic
│   │   ├── source_index_service.py # NLM source card generation pipeline
│   │   └── __init__.py
│   ├── tests/                      # pytest test suite
│   ├── main.py                     # FastAPI entry point & router registration
│   ├── requirements.txt
│   └── requirements_dev.txt
│
├── spo_frontend/                   # Frontend Assets & Pages
│   ├── templates/                  # Jinja2 HTML templates (served by FastAPI)
│   ├── static/
│   │   ├── css/                    # spo_global.css (tokens) + per-page CSS
│   │   └── js/                     # api.js, source_library_api.js + per-page JS
│   ├── new_pages_already_migrated/ # FastAPI page routers (Jinja2-serving)
│   │   ├── app_home_page.py        # GET /app
│   │   ├── thesis_setup_page.py    # GET /thesis-setup
│   │   ├── source_library_page.py  # GET /source-library
│   │   └── write_section.py        # GET /write-section
│   ├── streamlit_pages_about_to_be_migrated/  # Legacy — to be phased out
│   │   └── 4_Consistency_Chain.py
│   ├── api.py                      # Streamlit-only API client (@st.cache_data)
│   ├── ui.py                       # Streamlit shared UI helpers
│   └── app.py                      # Streamlit entry point (legacy)
│
├── scripts/                        # Standalone diagnostic/maintenance scripts
├── docs/                           # Feature documentation & API references
├── architecture.md
├── AGENTS.md
├── RULES.md
├── .env                            # Never commit
└── .env.example
```

> `spo_data/` (actual location: `C:/Users/TUSHAR/spo_data`) is created at runtime by `storage.py` — not in the repo.

---

## Data Persistence

All data lives under `SPO_DATA_DIR` (env var; actual path: `C:/Users/TUSHAR/spo_data`). Supports multi-thesis layout: empty `thesis_id` = root; named `thesis_id` = `theses/{thesis_id}/`.

```
spo_data/
├── thesis_context/synopsis.json, chapters/chapter_01.json
├── source_groups/{group_id}/group_meta.json, sources/{source_id}.json
├── consistency_chain/{chapter_id}/{subtopic_id}.json
├── notes/{scope}/{note_id}.json
├── sections/{chapter_id}/{subtopic_id}_draft.json, {subtopic_id}_nlm_state.json
├── misc/drive_scan_result.json, source_index_{safe_name}.json, batch_{batch_id}.json
└── theses/{thesis_id}/            # mirrors root layout for named theses
```

---

## Migration Status

| Page | Status |
|---|---|
| App Home | ✅ Migrated → `/app` |
| Thesis Setup | ✅ Migrated → `/thesis-setup` |
| Source Library | ✅ Migrated → `/source-library` |
| Write Section | ✅ Migrated → `/write-section` |
| Consistency Chain | ⏳ In `streamlit_pages_about_to_be_migrated/` |

---

## Environment Variables

| Variable | Default |
|---|---|
| `SPO_DATA_DIR` | `C:/Users/TUSHAR/spo_data` |
| `SPO_API_URL` | `http://localhost:8000` |
| `GOOGLE_SERVICE_ACCOUNT_FILE` | — |
| `SPO_NLM_EMAIL` | — |
| `SPO_NLM_PASSWORD` | — |
| `NOTEBOOKLM_AUTH_JSON` | — |

Never hardcode any of these. They belong in `.env`.

---

## API & Wiring Rules

**Backend:** Routers handle HTTP only — all business logic and IO lives in `services/`. All endpoints accept `thesis_id` as `Query("")`; empty string = default thesis. Raise `HTTPException(status_code=..., detail="...")`. Return data directly — never `{"success": bool}`.

**Frontend (Jinja2):** No `fetch()` in page JS files — all calls go through the page's API module (`api.js` for write_section, `source_library_api.js` for source_library). `thesis_id` is read from `localStorage.getItem("spo_active_thesis")` and injected by `_p()` in both modules. Page-specific CSS goes in `static/css/<page>.css`; shared tokens go in `spo_global.css`.

**Frontend (Streamlit/Legacy):** All HTTP calls go through `spo_frontend/api.py`. Shared UI components live in `spo_frontend/ui.py`. Read-only functions use `@st.cache_data`; mutations call `.clear()`. **Streamlit is read-only for new features** — all new pages must be Jinja2.

**Naming:** Python snake_case everywhere; Pydantic models PascalCase; JS functions camelCase; API route paths kebab-case; constants UPPER_SNAKE_CASE.

---

## Constraints

- Only modify files directly related to the current task — ask before touching anything outside scope
- Never touch: `.env`, `spo_data/`, service account files — unless explicitly told to
- Never rename files, folders, or reorganise structure unless explicitly asked
- Never install a new pip package without asking first
- Never assume an API endpoint exists — verify in the router file or at `/docs`
- Never hardcode secrets, file paths, URLs, or environment values
- Never leave placeholder comments in finished code
- Never add Streamlit code to any page already migrated to Jinja2
- Never split `notebooklm_service.py` or `storage.py` without being explicitly asked — both are intentionally large

---