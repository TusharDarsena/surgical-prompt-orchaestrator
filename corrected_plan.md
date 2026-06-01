# Implementation Plan: Migrate Consistency Chain to Jinja2

This is a comprehensive specification to transition the Consistency Chain dashboard from its legacy Streamlit architecture into the modern Jinja2 stack.

---

## Proposed Changes

### 1. Frontend - New Consistency Chain Page

#### 📂 `spo_frontend/new_pages_already_migrated/consistency_chain_page.py`
Create a new FastAPI page router to serve the Jinja2 template for the `/consistency-chain` route.
- Define `router = APIRouter()`.
- Use `Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))` to properly resolve the templates path.
- Provide `api_base`, `active_page`, and an empty `chapters` array for server-side rendering fallback context to prevent layout shifts.

#### 📂 `spo_frontend/templates/consistency_chain.html`
Create the structured HTML template.
- Extend `base.html`.
- Utilize `{% block logo_suffix %}` and `{% block breadcrumb %}` for navigation integration.
- Structure main layout inside `{% block content %}` with utility wrappers (`.thesis-strip`, `.context-strip`) mirroring `write_section.html`.
- Include UI elements: `#thesisSelect`, `#chapterSelect`, a metrics row (`#metricsRow`), and a thread section (`#threadContainer`).
- **Critical Fix:** Ensure `<link>` and `<script type="module">` tags are placed properly inside the `{% block extra_css %}` and `{% block page_script %}` template blocks, respectively.

#### 📂 `spo_frontend/static/js/consistency_chain.js`
Implement the core workflow client-side. Follow the established layered approach (`api.js` for fetches, DOM handlers, state, render).
- **Import Style:** Use `import * as API from "./api.js";` to match project conventions.
- **Initialization:** Load `spo_theses` from localStorage and populate the `#thesisSelect` dropdown. **Explicitly set the dropdown value to match `localStorage.getItem("spo_active_thesis")` on load to prevent visual de-sync.** Listen for changes to update `spo_active_thesis` and reload chapters.
- **Chapter Mapping Workflow:** Fetch chapters via `API.listChapters()`, cache them in a module-scoped variable `cachedChapters` for fast memory lookup, and populate the `#chapterSelect` dropdown. Auto-load the first chapter. **Crucially, add a `change` event listener to `#chapterSelect` that extracts `event.target.value` and passes it to `loadChain()`.**
- **Thread Matrix Pipeline:** Call `API.getChainForChapter(chapterId)` (extracting the `chain` array from the response object to prevent TypeErrors). Compute completion metrics (use ternary operator to prevent zero-division NaN errors). Render `.thread-block` items based on state:
  - If a section is complete, render the summary.
  - If pending, show the "⬜ Pending" state and add the exact caption: "Not yet written. Go to **Write a Section** to complete this subtopic."
  - **Always display the subtopic's goal (`sub.goal`) prominently at the top of the detail block.**
- **Empty States:** Include explicit DOM manipulations to show friendly messages if there are no chapters ("No chapters yet. Set up your thesis first.") or no subtopics ("No subtopics defined in this chapter.").
- **In-Place Mutation Handling:** Add a `🗑️ Delete Summary` button for completed blocks that calls `API.deleteConsistencySummary()`. Refresh the thread visually by calling `loadChain(chapterId)` in-place without a hard browser reload.
- **Markdown Export:** Generate a structured Markdown string of the argument thread when `#copyButton` is pressed. Initialize the string with `# Argument Thread — [Chapter Title]`, then map over the chain and construct the Markdown using exact Pydantic fields (`subtopic_number`, `subtopic_title`, `core_argument_made`, and `key_terms_established`).

#### 📂 `spo_frontend/static/css/consistency_chain.css`
Style the modern container modules utilizing the visual structure defined by design token rules in `spo_global.css`.
- Use grid and flexbox for layout structure alignment.
- Customize the progress bar to use primary tokens (`var(--primary)`).
- Apply solid colored edge borders matching `var(--success)` for completed items and `var(--text-muted)` for pending ones.
- Style the plain-text markdown export component to span full workspace width using rigid monospace formatting.

---

### 2. Frontend - Shared Assets

#### 📂 `spo_frontend/static/js/api.js`
Append the surgical consistency record deletion mutation endpoint.
- Export `deleteConsistencySummary(chapterId, subtopicId)` which calls `_delete(_p('/consistency/${chapterId}/${subtopicId}'))` to preserve the thesis context parameter safely.

#### 📂 `spo_frontend/templates/app_home.html`
Fix the navigation card link to route to the new Jinja page.
- Update the Consistency Chain `<a href>` from `/consistency` to `/consistency-chain`.

---

### 3. Backend - Routing Infrastructure

#### 📂 `spo_backend/main.py`
Register the newly structured Jinja2 rendering pipeline endpoint into the root backend lifecycle process.
- Import `consistency_chain_page`.
- Inject the global `_templates` context object into the router to enforce uniform resolving.
- Mount the router on the `app` using `app.include_router()`.

---

## Cleanup: Dead Code Removal

Remove all redundant server-rendered files from the framework migration layout.
Execute the following in PowerShell from the workspace root context folder location:

```powershell
Remove-Item -Recurse -Force "spo_frontend\streamlit_pages_about_to_be_migrated"
Remove-Item -Force "spo_frontend\app.py"
Remove-Item -Force "spo_frontend\api.py"
Remove-Item -Force "spo_frontend\ui.py"
Remove-Item -Force "spo_frontend\requirements.txt"
```

---

## Verification Plan

1. **System Spin-up:** Run `uvicorn spo_backend.main:app --reload --port 8000` from the workspace root.
2. **Page Delivery Route Execution:** Navigate to `http://localhost:8000/consistency-chain`.
3. **Multi-Thesis Scope Switch Test:** Check that changing the `Active Thesis` dropdown modifies the content mapping index structures correctly.
4. **Layout Checkpoint Traversal:** Verify that switching the chapter drop-down resets and prints the corresponding narrative thread summary timeline dynamically.
5. **Zero-Safe Layout Execution Check:** Open a freshly structured chapter with zero active subtopics; confirm that it reports a `0%` progress bar state cleanly without NaN artifacts.
6. **Surgical Chain Deletion Test:** Select a section summary card execution block, click `🗑️ Delete Summary`, confirm the warning popup, and verify that the target section re-renders into a `Pending` state.
7. **Markdown Export Evaluation:** Click `📋 Copy Full Thread`. Paste the clipboard buffer array into a raw layout editor to ensure it outputs a perfectly formed `# Argument Thread` header.
