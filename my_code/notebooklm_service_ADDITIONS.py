# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ADDITIONS TO: spo_backend/services/notebooklm_service.py
# INSERT LOCATION: after the "# ── Core sequences" block, at the end of the file
#                  after suggest_summary_service()
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# ── Index card generation — prompt path ───────────────────────────────────────
_SERVICE_FILE     = os.path.abspath(__file__)
_SERVICES_DIR     = os.path.dirname(_SERVICE_FILE)
_BACKEND_DIR_SVC  = os.path.dirname(_SERVICES_DIR)
_PROJECT_ROOT_SVC = os.path.dirname(_BACKEND_DIR_SVC)
_GENERATE_SOURCE_PROMPT_PATH = os.path.join(
    _PROJECT_ROOT_SVC, "prompts", "generate_source_json.txt"
)

# ── IC run locks (separate namespace from write-section locks) ─────────────────
_ic_run_locks: dict[str, asyncio.Lock] = {}
_ic_locks_registry_lock = asyncio.Lock()


async def _get_ic_run_lock(thesis_name: str) -> asyncio.Lock:
    async with _ic_locks_registry_lock:
        if thesis_name not in _ic_run_locks:
            _ic_run_locks[thesis_name] = asyncio.Lock()
        return _ic_run_locks[thesis_name]


async def is_ic_run_active(thesis_name: str) -> bool:
    """Public interface for the router to check whether an IC run lock is held."""
    lock = await _get_ic_run_lock(thesis_name)
    return lock.locked()


# ── PDF filter ─────────────────────────────────────────────────────────────────
# Keywords whose files should be included alongside chapter PDFs.
# 'summary' was added to source_resolver._KEYWORD_MAP to support this.
_IC_KEEP_KEYWORDS = {"title page", "abstract", "conclusion", "introduction", "summary"}


def _filter_chapter_pdfs(files: list[str]) -> list[str]:
    """
    Returns only the chapter PDFs (and relevant front/back matter) from a thesis folder.

    Keep rules (applied in order per file):
      1. Has a chapter number  → KEEP  (e.g. 07_chapter 1.pdf)
      2. Has a keep keyword    → KEEP  (e.g. 07_abstract.pdf, 10_conclusion.pdf)
      3. Everything else       → SKIP  (certificate, declaration, bibliography, etc.)

    Delegates all parsing to source_resolver._parse_filename so there is
    exactly one place where filename classification logic lives.
    """
    from services.source_resolver import _parse_filename

    kept = []
    for f in files:
        if not f.lower().endswith(".pdf"):
            continue
        parsed = _parse_filename(f)
        if parsed["number"] is not None:
            kept.append(f)
        elif parsed["keyword"] in _IC_KEEP_KEYWORDS:
            kept.append(f)
        else:
            logger.debug(f"IC filter: skipping '{f}' (number={parsed['number']}, keyword={parsed['keyword']})")
    return kept


# ── Index card generation sequence (one thesis folder) ────────────────────────

async def _generate_index_card_sequence(
    thesis_name: str,
    batch_id: Optional[str] = None,
) -> None:
    """
    Background task. Full automation loop for one thesis folder:
      1. Read scan entry → get folder_path + files
      2. Filter PDFs to chapters only
      3. Create NLM notebook, upload filtered PDFs
      4. Send generate_source_json.txt prompt
      5. Parse JSON response, save raw JSON to disk
      6. Call do_auto_import() → writes source group + index cards to SPO
      7. Update drive_scan_result import_status
      8. Write final IC run state

    Holds the IC run lock for its entire duration.
    All exceptions are caught internally — never raises.
    """
    ic_lock = await _get_ic_run_lock(thesis_name)

    async with ic_lock:
        state_key = f"ic_run_{thesis_name}"
        state: dict = {
            "thesis_name": thesis_name,
            "status": "running",
            "started_at": datetime.utcnow().isoformat(),
            "completed_at": None,
            "notebook_id": None,
            "files_uploaded": [],
            "files_failed": [],
            "imported_group_id": None,
            "sources_created": 0,
            "json_path": None,
            "error": None,
            "batch_id": batch_id,
        }
        storage.write_misc(state_key, state)

        try:
            # ── Step 1: Read scan entry ────────────────────────────────────
            scan = storage.read_misc("drive_scan_result") or {}
            thesis_entry = scan.get(thesis_name)
            if not thesis_entry:
                raise RuntimeError(
                    f"Thesis '{thesis_name}' not found in drive scan. "
                    "Run POST /drive/scan-local first."
                )

            folder_path = (
                thesis_entry.get("folder_path")
                or thesis_entry.get("level2_path", "")
            )
            all_files = thesis_entry.get("files", [])

            # ── Step 2: Filter PDFs ────────────────────────────────────────
            filtered = await asyncio.to_thread(_filter_chapter_pdfs, all_files)
            if not filtered:
                raise RuntimeError(
                    f"No uploadable PDFs after filtering. "
                    f"All {len(all_files)} file(s) were skipped (certificates, bibliography, etc.). "
                    "Check that the folder contains chapter PDFs."
                )

            logger.info(
                f"IC '{thesis_name}': {len(filtered)}/{len(all_files)} files selected for upload"
            )

            # ── Step 3: Read prompt from disk ──────────────────────────────
            if not os.path.isfile(_GENERATE_SOURCE_PROMPT_PATH):
                raise RuntimeError(
                    f"Prompt file not found at: {_GENERATE_SOURCE_PROMPT_PATH}. "
                    "Ensure prompts/generate_source_json.txt exists in the project root."
                )
            with open(_GENERATE_SOURCE_PROMPT_PATH, "r", encoding="utf-8") as f:
                prompt_text = f.read()

            # ── Step 4–6: All NLM API calls inside one client context ──────
            async with _nlm_client() as client:

                # Create notebook
                notebook_title = f"SPO — Source Cards — {thesis_name[:60]}"
                nb = await client.notebooks.create(notebook_title)
                notebook_id = nb.id
                logger.info(f"IC: Created notebook '{notebook_id}' for '{thesis_name}'")

                state["notebook_id"] = notebook_id
                storage.write_misc(state_key, state)

                # Upload filtered PDFs
                uploaded: list[str] = []
                failed: list[dict] = []

                for file_name in filtered:
                    abs_path = os.path.join(folder_path, file_name)

                    if not file_name.lower().endswith(".pdf"):
                        failed.append({"file": file_name, "reason": "not a PDF"})
                        continue

                    if not os.path.isfile(abs_path):
                        failed.append({
                            "file": file_name,
                            "reason": f"file not found at: {abs_path}",
                        })
                        logger.warning(f"IC: File not found: {abs_path}")
                        continue

                    try:
                        await client.sources.add_file(notebook_id, abs_path, wait=True)
                        uploaded.append(file_name)
                        logger.info(f"IC: Uploaded '{file_name}'")
                    except Exception as e:
                        failed.append({"file": file_name, "reason": str(e)})
                        logger.warning(f"IC: Upload failed for '{file_name}': {e}")

                    await asyncio.sleep(2)   # rate-limit buffer — matches _run_sequence

                state["files_uploaded"] = uploaded
                state["files_failed"] = failed
                storage.write_misc(state_key, state)

                if not uploaded:
                    raise RuntimeError(
                        "All PDF uploads failed. Cannot generate index cards. "
                        f"Failed files: {[f['file'] for f in failed]}"
                    )

                # Send the extraction prompt
                logger.info(f"IC: Sending prompt to notebook '{notebook_id}'")
                result = await client.chat.ask(notebook_id, prompt_text)
                raw_response = result.answer

                if not raw_response or not raw_response.strip():
                    raise RuntimeError(
                        "NotebookLM returned an empty response. "
                        "Sources may still be processing — wait 30 s and retry."
                    )

            # ── Step 5: Parse JSON ─────────────────────────────────────────
            # Strip markdown fences — NLM sometimes wraps JSON despite instructions.
            # Reuses same pattern as suggest_summary_service.
            clean = re.sub(r"```(?:json)?|```", "", raw_response).strip()
            try:
                parsed_json = json.loads(clean)
            except (json.JSONDecodeError, ValueError) as e:
                raise RuntimeError(
                    f"Could not parse NLM response as JSON: {e}. "
                    f"First 300 chars of response: {raw_response[:300]}"
                )

            # ── Step 6: Save raw JSON to disk ──────────────────────────────
            # Keeps a recovery copy — if do_auto_import fails you can re-import
            # manually from Source Library without re-running NLM.
            index_cards_dir = os.path.join(folder_path, "index_cards")
            os.makedirs(index_cards_dir, exist_ok=True)
            safe_name = re.sub(r'[/\\:*?"<>|]', "_", thesis_name)[:80]
            json_path = os.path.join(index_cards_dir, f"{safe_name}.json")
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(parsed_json, f, indent=2, ensure_ascii=False)
            logger.info(f"IC: Saved raw JSON to '{json_path}'")

            # ── Step 7: Import to SPO ──────────────────────────────────────
            from services.source_importer import do_auto_import
            import_result, import_error = await asyncio.to_thread(
                do_auto_import, data=parsed_json, thesis_id="", scan_key=thesis_name
            )
            if import_error:
                raise RuntimeError(f"do_auto_import failed: {import_error}")

            # ── Step 8: Update scan entry import_status ────────────────────
            # Re-read scan to avoid overwriting concurrent changes.
            scan = storage.read_misc("drive_scan_result") or {}
            if thesis_name in scan:
                scan[thesis_name]["import_status"] = {
                    "imported": True,
                    "imported_at": datetime.utcnow().isoformat(),
                    "group_id": import_result["group_id"],
                    "error": None,
                    "json_path": json_path,
                }
                storage.write_misc("drive_scan_result", scan)

            # ── Done ───────────────────────────────────────────────────────
            state.update({
                "status": "done",
                "completed_at": datetime.utcnow().isoformat(),
                "imported_group_id": import_result["group_id"],
                "sources_created": import_result["sources_created"],
                "json_path": json_path,
                "error": None,
            })
            storage.write_misc(state_key, state)
            logger.info(
                f"IC: Complete for '{thesis_name}' — "
                f"{import_result['sources_created']} sources created, "
                f"group '{import_result['group_id']}'"
            )

        except Exception as e:
            logger.error(f"IC: Generation failed for '{thesis_name}': {e}", exc_info=True)
            state.update({
                "status": "error",
                "completed_at": datetime.utcnow().isoformat(),
                "error": str(e),
            })
            storage.write_misc(state_key, state)


# ── Index card batch sequence ──────────────────────────────────────────────────

async def _generate_index_card_batch_sequence(
    batch_id: str,
    thesis_names: list[str],
) -> None:
    """
    Splits thesis_names into two halves and runs them in parallel —
    each half processed sequentially within its worker.
    Mirrors _run_batch_sequence exactly.
    """
    mid = math.ceil(len(thesis_names) / 2)
    worker_a = thesis_names[:mid]
    worker_b = thesis_names[mid:]

    async def _worker(names: list[str]) -> None:
        for name in names:
            await _generate_index_card_sequence(name, batch_id=batch_id)

    try:
        await asyncio.gather(_worker(worker_a), _worker(worker_b))
        final_status = "done"
    except Exception as e:
        logger.error(f"IC batch '{batch_id}' unexpected error: {e}", exc_info=True)
        final_status = "error"

    batch_state = storage.read_misc(f"ic_batch_{batch_id}") or {}
    batch_state.update({
        "status": final_status,
        "completed_at": datetime.utcnow().isoformat(),
    })
    storage.write_misc(f"ic_batch_{batch_id}", batch_state)
