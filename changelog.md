# Changelog — Surgical Prompt Orchestrator (SPO)

All notable changes to this project will be documented in this file.

## [2026-05-15] - Initial Session & Planning

### Added
- Created `changelog.md` to track session progress.
- Created `decisions.md` to document system design choices and reasoning.
- Created `implementation_plan.md` for "Automated Source Card JSON Batch Onboarding" feature.

### Planned
- Automated Source Card JSON Batch Onboarding:
  - Phase A: Prompt-helper with paste-back UI.
  - Phase B: Full NotebookLM automation (upload → prompt → import → cleanup).
- Refactoring `drive.py` and `source_library.js` to support the new indexing flow.
- New `source_index_service.py` for handling background indexing jobs.
