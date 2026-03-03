# SPO — Surgical Prompt Orchestrator

A personal academic writing tool. Not an AI. A **prompt stitching engine**.

It solves one problem: Claude and NotebookLM are powerful but stateless and blind.
Claude has never seen your PDFs. NotebookLM forgets the argument it made last section.
SPO bridges both gaps through structured curation — not automation.

---

## Core Principle

> You bring the thinking. SPO brings the structure.

The app holds:
- Your thesis's master argument (synopsis)
- Your chapter goals and subtopic definitions
- Your hand-curated summaries of every source (index cards)
- A running log of what was argued in each completed section (consistency chain)

It stitches these into two prompts per subtopic — one for Claude, one for NotebookLM.

---

## The Two-Prompt Workflow

Every subtopic goes through exactly this sequence:

```
PHASE 1 — ARCHITECT (Claude)
─────────────────────────────────────────────────────────
1. GET  /compile/architect-prompt/{chapter_id}/{subtopic_id}
        → Compiles: synopsis + chapter goal + subtopic + source index cards
                    + previous section summary

2. Paste into Claude
        → Claude outputs Task.md (structural blueprint)

3. Edit Task.md in your editor
        → You remove fluff, adjust arguments, verify source citations

4. POST /tasks/{chapter_id}/{subtopic_id}
        → Save the approved Task.md


PHASE 2 — WRITING (NotebookLM)
─────────────────────────────────────────────────────────
5. GET  /compile/notebooklm-prompt/{chapter_id}/{subtopic_id}
        → Compiles: Task.md + previous section summary + writing rules

6. Upload relevant PDFs to NotebookLM

7. Paste prompt into NotebookLM
        → NotebookLM writes the draft using only your uploaded sources

8. Review and approve the draft

9. POST /consistency/{chapter_id}/{subtopic_id}
        → Save a summary of what was argued
        → This becomes the "previous section context" for the next subtopic
```

---

## Data Model

```
spo_data/                          ← ~/spo_data by default
│
├── thesis_context/
│   ├── synopsis.json
│   └── chapters/
│       ├── chapter_01.json        ← chapter goal + subtopics list
│       └── chapter_02.json
│
├── source_groups/
│   └── {group_id}/                ← one complete work (thesis, book, etc.)
│       ├── group_meta.json
│       └── sources/
│           └── {source_id}.json   ← one PDF/chapter + index card
│
├── notes/
│   ├── thesis/                    ← free-text notes on your own thesis
│   ├── source_group/              ← overall notes on a source work
│   ├── source/                    ← notes on a specific chapter/PDF
│   └── chapter/                   ← notes on your own chapters
│
├── task_blueprints/
│   └── chapter_01__1_3_2.json    ← approved Task.md per subtopic
│
└── consistency_chain/
    └── chapter_01/
        └── 1_3_2.json            ← what was argued, for injecting forward
```

---

## API Reference

### Setup & Health
```
GET  /                             status + data dir
GET  /health
```

### Thesis Context
```
POST   /thesis/synopsis
GET    /thesis/synopsis
PATCH  /thesis/synopsis

POST   /thesis/chapters
GET    /thesis/chapters
GET    /thesis/chapters/{chapter_id}
PATCH  /thesis/chapters/{chapter_id}
DELETE /thesis/chapters/{chapter_id}

POST   /thesis/chapters/{chapter_id}/subtopics
PATCH  /thesis/chapters/{chapter_id}/subtopics/{subtopic_id}
DELETE /thesis/chapters/{chapter_id}/subtopics/{subtopic_id}
GET    /thesis/chapters/{chapter_id}/subtopics/{subtopic_id}/suggested-sources
```

### Source Library
```
POST   /sources/groups
GET    /sources/groups
GET    /sources/groups/{group_id}
PATCH  /sources/groups/{group_id}
DELETE /sources/groups/{group_id}

POST   /sources/groups/{group_id}/sources
GET    /sources/groups/{group_id}/sources
GET    /sources/groups/{group_id}/sources/{source_id}
PATCH  /sources/groups/{group_id}/sources/{source_id}
DELETE /sources/groups/{group_id}/sources/{source_id}

POST   /sources/groups/{group_id}/sources/{source_id}/index-card
GET    /sources/groups/{group_id}/sources/{source_id}/index-card
PATCH  /sources/groups/{group_id}/sources/{source_id}/index-card
DELETE /sources/groups/{group_id}/sources/{source_id}/index-card

GET    /sources/ready
GET    /sources/search/by-theme/{theme}
```

### Notes (free-text)
```
POST   /notes/{scope}/{entity_id}             scope: thesis|source_group|source|chapter
GET    /notes/{scope}/{entity_id}
PATCH  /notes/{scope}/{entity_id}/{note_id}
DELETE /notes/{scope}/{entity_id}/{note_id}
```

### Task Blueprints
```
POST   /tasks/{chapter_id}/{subtopic_id}      save approved Task.md
GET    /tasks/{chapter_id}/{subtopic_id}
GET    /tasks/
DELETE /tasks/{chapter_id}/{subtopic_id}
```

### Prompt Compiler
```
GET    /compile/architect-prompt/{chapter_id}/{subtopic_id}    auto source detection
POST   /compile/architect-prompt/{chapter_id}/{subtopic_id}    manual source selection

GET    /compile/notebooklm-prompt/{chapter_id}/{subtopic_id}
POST   /compile/notebooklm-prompt/{chapter_id}/{subtopic_id}   with style overrides
```

### Consistency Chain
```
POST   /consistency/{chapter_id}/{subtopic_id}
GET    /consistency/{chapter_id}
GET    /consistency/{chapter_id}/{subtopic_id}
GET    /consistency/{chapter_id}/previous-for/{subtopic_id}
DELETE /consistency/{chapter_id}/{subtopic_id}
```

---

## Setup

```bash
pip install -r requirements.txt
cd spo_backend
uvicorn main:app --reload --port 8000
```

Docs: http://localhost:8000/docs

Override data directory:
```bash
SPO_DATA_DIR=/path/to/your/data uvicorn main:app --reload
```

---

## Index Card Quality

The index card is the most important thing you write in this system.
Claude generates Task.md blueprints based entirely on your index cards.
Vague cards produce generic blueprints.

**Bad key_claim:** "Discusses women in Indian literature."
**Good key_claim:** "Argues pre-1947 male-authored texts constructed female characters
as nationalist symbols, systematically erasing individual agency ('nationalist idealization')."

**Bad limitation:** "Old source."
**Good limitation:** "Covers only Bankimchandra and Tagore. Cannot support claims
about pan-Indian or non-Bengali literary tradition."

Write index cards only when you need the source for an upcoming section.
Use notes for everything else — raw reading impressions, copied passages, ideas.

---

## Notes vs Index Cards

| | Notes | Index Cards |
|---|---|---|
| When to write | While reading, immediately | Before writing the section |
| Structure | None — paste anything | Structured fields |
| Injected into prompts | No | Yes |
| Purpose | Your scratch pad | Claude's input |

---

# SPO — Architecture Changes

## What Changed and Why

### 1. Synopsis setup — form replaced by JSON upload

**Old:** POST /thesis/synopsis with 6 fields (title, author, field, theoretical framework, central argument, scope and limits).

**New:** POST /import/thesis accepts a full thesis.json. The JSON is richer — it carries research question, objectives, methodology, key authors, central themes, chapter structure overview, and more. SPO stores the whole thing. Only the core_argument, theoretical_frameworks, and temporal_scope are injected into architect prompts. The rest is stored for reference.

**Why:** A 6-field form cannot express a 19-page synopsis. The JSON is prepared once using an LLM to compress your synopsis document, reviewed by you, then uploaded.

---

### 2. Chapter setup — form replaced by chapterization.json

**Old:** POST /thesis/chapters + POST /thesis/chapters/{id}/subtopics, filled manually field by field.

**New:** POST /import/chapterization/{chapter_id} accepts a single chapterization.json containing two things:
- Topics and subtopics (number, title, goal, position_in_argument)
- A chapter arc (150–200 words describing how all subtopics connect argumentatively)

**Why:** The chapter arc is a new concept not present in the old architecture. Without it, Claude generating Task.md for any subtopic has no map of where the chapter's argument is going — it fills that gap with AI fluff. The arc constrains Claude to the specific argumentative role each subtopic must play.

The chapter arc is injected into every architect prompt for that chapter alongside the synopsis layer.

---

### 3. Source setup — form replaced by source.json

**Old:** POST /sources/groups → then POST /sources/groups/{id}/sources → then POST /sources/.../index-card, one at a time.

**New:** POST /import/source accepts a single source.json per external work. The JSON contains:
- Top-level metadata and a summary of the whole work
- One section per chapter with key claims, themes, limitations, and relevant_subtopics tags

A source.json for a 6-chapter thesis becomes 1 SourceGroup + 6 Sources + 6 IndexCards in one upload.

**Why:** The old flow was too slow. Index cards prepared manually from scratch are also low quality. The new flow: upload source PDFs chapter by chapter to NotebookLM → extract structured summaries → review and correct → import to SPO. NotebookLM is used for extraction (grounded in the actual document), not generation.

---

### 4. New field on Chapter model — chapter_arc

The Chapter model gains a `chapter_arc` text field. This is populated by the chapterization.json import. It is injected into the architect prompt as a new Section 2 (between thesis context and subtopic goal).

---

### 5. Architect prompt — one new section added

**Old sections:** Thesis Context → Previous Section → Source Profiles → Instructions

**New sections:** Thesis Context → **Chapter Arc** → Current Subtopic → Previous Section → Source Profiles → Instructions

The chapter arc section tells Claude how all subtopics of this chapter connect and what specific argumentative role the current subtopic must play. This is the primary mechanism for preventing generic Task.md output.

---

### 6. _gather_payload and _render_prompt — changes required

**_gather_payload:** Must additionally load the chapter_arc from the chapter record and include it in the payload dict.

**_render_prompt:** Must render the chapter arc as a new section between thesis context and subtopic. The arc text is injected with explicit framing — Claude is told this is the argumentative map of the chapter and that the current subtopic must stay within its designated role.

---

## New Endpoints Required

```
POST /import/thesis
POST /import/chapterization/{chapter_id}
POST /import/source
GET  /import/status
```

Old form-based endpoints remain for manual patches and corrections but are no longer the primary setup path.

---

## What Is Unchanged

- The two-prompt workflow (Architect → NotebookLM)
- Task blueprint storage and approval flow (tasks.py)
- Consistency chain (consistency.py)
- Notes (notes.py)
- Storage layer structure (storage.py) — new fields slot in without restructuring
- NotebookLM prompt compiler (_render_notebooklm_prompt) — no changes needed

## Future Extensions

- Book ingestion helper — paste chapter text, get suggested index card fields
- Theme explorer — which themes are covered/gaps in your source library
- Export — compile full chapter context as a single document