# SPO — Surgical Prompt Orchestrator

A personal academic writing assistant. **Not an AI**. A prompt stitching engine.

---

## What This Is

SPO solves one problem: generating prompts so precise that Claude and NotebookLM
produce grounded, consistent, non-fluffy academic writing — section by section.

This backend manages three things:

1. **Your thesis context** — synopsis, chapters, subtopics. The "big picture" that never leaves the prompt.
2. **Source library** — your external PDFs catalogued with hand-written index cards.
3. **Consistency chain** — summaries of what was argued in previous sections, injected forward.

Zero API calls. Zero database. JSON files on your hard drive.

---

## Core Principle

> Claude is blind to your PDFs. NotebookLM has no memory between sessions.
> This app bridges both gaps — not with automation, but with structured curation.

The Architect Mega-Prompt Claude receives contains:
- Your thesis synopsis (the master argument)
- The chapter goal (what this chapter must prove)
- The subtopic definition (the specific section)
- Index cards of relevant sources (YOUR summary of what each PDF says)

NotebookLM receives:
- The approved Task.md (the structural blueprint)
- Previous section summary (so it doesn't restart its logic)
- A hard instruction to use only the uploaded PDFs

---

## Data Model

```
spo_data/                          ← ~/spo_data by default
│
├── thesis_context/
│   ├── synopsis.json              ← Your thesis's master argument
│   └── chapters/
│       ├── chapter_01.json        ← Chapter goal + list of subtopics
│       └── chapter_02.json
│
├── source_groups/
│   └── {group_id}/                ← One complete work (thesis, book, etc.)
│       ├── group_meta.json        ← Author, title, year, type
│       └── sources/
│           └── {source_id}.json   ← One PDF/chapter + its index card
│
└── consistency_chain/
    └── {chapter_id}/
        └── {subtopic_id}.json     ← What was argued, for injecting into next section
```

### Why SourceGroup → Source?

A PhD thesis has 6 chapters. If you upload them as 6 PDFs, they still belong to
"Sharma 2003." The SourceGroup holds that intellectual relationship. When you need
"everything from Sharma," you pull one group.

### Why human-written index cards?

Because AI-generated summaries miss what *you* need. The index card is your
curation layer. You decide which claims are relevant to your argument, which
subtopics this source supports, and what it cannot support. This specificity
is what makes the Architect Mega-Prompt generate grounded Task.md blueprints
instead of generic AI outlines.

---

## Setup

```bash
pip install fastapi uvicorn pydantic

cd spo_backend
uvicorn main:app --reload --port 8000
```

API docs: http://localhost:8000/docs

Override data directory:
```bash
SPO_DATA_DIR=/path/to/your/data uvicorn main:app --reload --port 8000
```

---

## API Overview

### Thesis Context
```
POST   /thesis/synopsis                                    ← Write once
GET    /thesis/synopsis
PATCH  /thesis/synopsis

POST   /thesis/chapters                                    ← One per chapter
GET    /thesis/chapters
GET    /thesis/chapters/{chapter_id}
POST   /thesis/chapters/{chapter_id}/subtopics             ← One per subtopic
PATCH  /thesis/chapters/{chapter_id}/subtopics/{id}
GET    /thesis/chapters/{chapter_id}/subtopics/{id}/suggested-sources
```

### Source Library
```
POST   /sources/groups                                     ← Register a work
GET    /sources/groups
GET    /sources/groups/{group_id}

POST   /sources/groups/{group_id}/sources                  ← Add a chapter/PDF
PATCH  /sources/groups/{group_id}/sources/{source_id}

POST   /sources/groups/{group_id}/sources/{id}/index-card  ← THE KEY STEP
GET    /sources/groups/{group_id}/sources/{id}/index-card
PATCH  /sources/groups/{group_id}/sources/{id}/index-card

GET    /sources/ready                                      ← All prompt-ready sources
GET    /sources/search/by-theme/{theme}
```

### Consistency Chain
```
POST   /consistency/{chapter_id}/{subtopic_id}             ← Save after writing
GET    /consistency/{chapter_id}                           ← Full chapter chain
GET    /consistency/{chapter_id}/previous-for/{subtopic_id} ← Inject into next prompt
```

---

## Workflow (Per Subtopic)

```
1. SELECT subtopic in your app (chapter_id + subtopic_id)

2. GET /thesis/chapters/{chapter_id}/subtopics/{id}/suggested-sources
   → App shows you which sources are tagged for this subtopic

3. GET /consistency/{chapter_id}/previous-for/{subtopic_id}
   → App gets the previous section's summary for context injection

4. App stitches: Synopsis + Chapter Goal + Subtopic + Source Index Cards
   → Architect Mega-Prompt is compiled. You copy it.

5. Paste into Claude. Claude outputs Task.md.

6. Paste Task.md into your app's editor. Review. Edit. Approve.

7. App compiles NotebookLM prompt:
   Task.md + Previous Section Summary + Writing Instructions
   → You copy. Upload relevant PDFs to NotebookLM. Paste prompt.

8. NotebookLM writes the draft.

9. You review draft. Save argument summary:
   POST /consistency/{chapter_id}/{subtopic_id}
   → Chain grows. Next subtopic has context.
```

---

## Index Card Quality Guide

A good index card is the difference between Claude generating a real blueprint
and generating generic AI prose.

**Bad key_claim:**
> "Discusses the role of women in Indian literature."

**Good key_claim:**
> "Argues that pre-1947 male-authored texts constructed female characters as
> nationalist symbols, systematically erasing their individual agency."

**Bad limitation:**
> "Old source."

**Good limitation:**
> "Focuses exclusively on Bengali literary tradition. Cannot support claims
> about pan-Indian feminist movement or Hindi/Urdu literary history."

**The themes field** uses snake_case tags (e.g. `nationalist_idealization`,
`partition_trauma`, `feminist_realism`) — these are how your app discovers
sources by topic, not just by subtopic assignment.

---

## Future Extensions (Planned)

- **Prompt Compiler endpoints** — assemble the full Architect Mega-Prompt and
  NotebookLM prompt as ready-to-copy text
- **Streamlit UI** — visual interface for all CRUD operations
- **Book ingestion helper** — paste chapter text, app suggests index card fields
- **Theme explorer** — visualize which themes are covered by which sources
