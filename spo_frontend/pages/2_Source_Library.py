"""
Page: Source Library
Two distinct workflows on this page:

1. INDEX CARD CREATOR (top section — new)
   Scan a local parent folder → see thesis folders + their PDFs →
   paste NotebookLM JSON output → save JSON + auto-import to SPO.

2. SOURCE LIBRARY BROWSER (bottom section — existing)
   Browse imported source groups, edit index cards, add notes.
"""

import json
import streamlit as st
import api
import ui

st.set_page_config(page_title="Source Library · SPO", page_icon="📖", layout="wide")
ui.page_header("📖 Source Library", "Create index cards from NotebookLM · Browse and edit imported sources.")

SOURCE_TYPES = ["thesis_chapter", "book_chapter", "journal_article", "book", "report", "other"]


# ══════════════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════

def _render_notes_section(scope: str, entity_id: str, key_prefix: str, pre_fetched_notes: list[dict]):
    notes = pre_fetched_notes
    notes_label = f"📝 Notes ({len(notes)})" if notes else "📝 Notes"

    st.markdown(f"**{notes_label}**")
    st.caption("Raw reading notes. Not injected into prompts — your private scratch pad.")

    for note in notes:
        n_id = note["note_id"]
        n_label = note.get("label") or "Note"
        with st.expander(n_label, expanded=False):
            updated_content = st.text_area(
                "Content", value=note.get("content", ""),
                height=150, key=f"note_content_{n_id}"
            )
            nc1, nc2 = st.columns(2)
            with nc1:
                if st.button("Save", key=f"save_note_{n_id}", use_container_width=True):
                    api.update_note(scope, entity_id, n_id, {
                        "label": n_label, "content": updated_content
                    })
                    ui.success("Note saved.")
                    st.rerun()
            with nc2:
                if st.button("🗑️ Delete", key=f"del_note_{n_id}", use_container_width=True):
                    api.delete_note(scope, entity_id, n_id)
                    st.rerun()

    with st.form(f"add_note_{key_prefix}"):
        n_lbl = st.text_input("Label (optional)", placeholder="Overall impressions",
                               key=f"nlbl_{key_prefix}")
        n_txt = st.text_area(
            "Paste your notes",
            height=150,
            placeholder="Paste reading notes, copied text, argument ideas — anything. No structure needed.",
            key=f"ntxt_{key_prefix}"
        )
        if st.form_submit_button("Save Note", use_container_width=True):
            if n_txt.strip():
                api.create_note(scope, entity_id, {"label": n_lbl or None, "content": n_txt})
                st.rerun()


def _render_index_card_form(group_id: str, source_id: str, has_card: bool, pre_fetched_card: dict | None):
    existing = pre_fetched_card if has_card else None

    with st.form(f"card_form_{source_id}"):
        default_claims = "\n".join(existing.get("key_claims", [])) if existing else ""
        claims_raw = st.text_area(
            "Key Claims ★  (one per line)",
            value=default_claims,
            height=150,
            help="2–5 specific claims this source makes. These go directly into compiled prompts.",
            placeholder=(
                "Argues pre-1947 male-authored texts constructed female characters as nationalist symbols\n"
                "Documents the 'representational gap' between literary depiction and lived experience"
            )
        )

        col1, col2 = st.columns(2)
        with col1:
            default_themes = ", ".join(existing.get("themes", [])) if existing else ""
            themes_raw = st.text_input(
                "Themes (comma-separated)",
                value=default_themes,
                placeholder="nationalist_idealization, representational_gap",
                help="Use snake_case. Used for searching sources by topic."
            )
            time_period = st.text_input(
                "Time Period Covered",
                value=existing.get("time_period_covered", "") if existing else "",
                placeholder="e.g. 1880–1947"
            )
        with col2:
            default_subs = ", ".join(existing.get("relevant_subtopics", [])) if existing else ""
            subtopics_raw = st.text_input(
                "Relevant Subtopics (comma-separated IDs)",
                value=default_subs,
                placeholder="1_3_2, 1_3_3",
                help="Subtopic IDs this source supports. Drives auto-suggestion in the compiler."
            )
            default_authors = ", ".join(existing.get("notable_authors_cited", [])) if existing else ""
            authors_raw = st.text_input(
                "Notable Scholars Cited",
                value=default_authors,
                placeholder="Chatterjee P., Bose M."
            )

        limitations = st.text_area(
            "Limitations ★",
            value=existing.get("limitations", "") if existing else "",
            height=80,
            placeholder="What can this source NOT support? e.g. 'Only covers Bengali literature.'",
            help="Feeds the 'Do Not Include' section of compiled prompts."
        )

        submitted = st.form_submit_button(
            "Update Index Card" if has_card else "Save Index Card",
            use_container_width=True,
            type="primary"
        )

        if submitted:
            claims = [c.strip() for c in claims_raw.strip().split("\n") if c.strip()]
            themes = [t.strip() for t in themes_raw.split(",") if t.strip()]
            if not claims or not themes:
                st.error("Key Claims and Themes are required.")
            else:
                data = {
                    "key_claims": claims,
                    "themes": themes,
                    "time_period_covered": time_period or None,
                    "relevant_subtopics": [s.strip() for s in subtopics_raw.split(",") if s.strip()],
                    "notable_authors_cited": [a.strip() for a in authors_raw.split(",") if a.strip()],
                    "limitations": limitations or None,
                }
                result = api.save_index_card(group_id, source_id, data, has_card)
                if result:
                    ui.success("Index card saved.")
                    st.rerun()

    if has_card:
        if st.button("🗑️ Delete Index Card", key=f"del_card_{source_id}"):
            api.delete_index_card(group_id, source_id)
            ui.success("Index card deleted.")
            st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — SOURCE LIBRARY BROWSER (existing)
# ══════════════════════════════════════════════════════════════════════════════

st.subheader("📚 Source Library")

# 🔥 Bulk fetch all groups, sources, cards, and notes in one fast API pass
library_data = api.get_library_view()
groups = library_data.get("groups", [])
notes_data = library_data.get("notes", {"source_group": {}, "source": {}})

if not groups:
    ui.info("No sources registered yet. Add a work above.")
    st.stop()

for group in groups:
    g_id = group["group_id"]
    source_count = group.get("source_count", 0)
    ready_count = group.get("ready_count", 0)
    status = f"📄 {source_count} docs · ✅ {ready_count} indexed"
    label = f"**{group['author']} ({group.get('year', '?')})** — {group['title']}  |  {status}"

    with st.expander(label, expanded=False):
        col_meta, col_edit, col_del = st.columns([4, 1, 1])
        with col_meta:
            st.caption(f"Type: {group.get('source_type', '?')} · {group.get('institution_or_publisher', '')}")
            if group.get("description"):
                st.markdown(f"*{group['description']}*")
        with col_edit:
            if st.button("✏️ Edit", key=f"edit_grp_btn_{g_id}"):
                st.session_state[f"editing_grp_{g_id}"] = True
        with col_del:
            if st.button("🗑️ Delete", key=f"del_grp_{g_id}"):
                api.delete_source_group(g_id)
                ui.success("Deleted.")
                st.rerun()

        if st.session_state.get(f"editing_grp_{g_id}"):
            with st.form(f"edit_grp_form_{g_id}"):
                st.markdown("**Edit Work Metadata**")
                ec1, ec2 = st.columns(2)
                with ec1:
                    e_desc = st.text_area("Description", value=group.get("description", "") or "", height=80)
                with ec2:
                    e_inst = st.text_input("Institution / Publisher", value=group.get("institution_or_publisher", "") or "")
                ef1, ef2 = st.columns(2)
                with ef1:
                    if st.form_submit_button("Save", use_container_width=True, type="primary"):
                        api.update_source_group(g_id, {
                            "description": e_desc or None,
                            "institution_or_publisher": e_inst or None,
                        })
                        st.session_state[f"editing_grp_{g_id}"] = False
                        ui.success("Updated.")
                        st.rerun()
                with ef2:
                    if st.form_submit_button("Cancel", use_container_width=True):
                        st.session_state[f"editing_grp_{g_id}"] = False
                        st.rerun()

        group_notes = notes_data.get("source_group", {}).get(g_id, [])
        _render_notes_section("source_group", g_id, f"grp_{g_id}", group_notes)

        st.divider()

        # Sources are securely embedded into the group payload
        sources = group.get("sources", [])

        with st.form(f"add_src_{g_id}"):
            st.markdown("**Add a Document (chapter / PDF)**")
            st.caption("SPO stores metadata only — the PDF itself goes to NotebookLM, not here.")
            ac1, ac2 = st.columns([1, 3])
            with ac1:
                s_label = st.text_input(
                    "Short Label ★", placeholder="Sharma Ch.2",
                    help="What Claude sees in the prompt. Keep it short.",
                    key=f"sl_{g_id}"
                )
                s_pages = st.text_input("Page Range", placeholder="45–89", key=f"sp_{g_id}")
            with ac2:
                s_title = st.text_input(
                    "Full Title / Section", key=f"st_{g_id}",
                    placeholder="Chapter 2: The Nationalist Imagination"
                )
                s_file = st.text_input(
                    "File name (for NotebookLM upload reference)",
                    placeholder="sharma_2003_ch2.pdf", key=f"sf_{g_id}"
                )

            if st.form_submit_button("Add Document", use_container_width=True):
                if not s_label or not s_title:
                    st.error("Label and Title are required.")
                else:
                    result = api.create_source(g_id, {
                        "label": s_label, "title": s_title,
                        "chapter_or_section": s_title,
                        "page_range": s_pages or None,
                        "file_name": s_file or None,
                    })
                    if result:
                        ui.success(f"Added: {s_label}")
                        st.rerun()

        if sources:
            st.markdown("**Documents in this work:**")
            for src in sources:
                s_id = src["source_id"]
                has_card = src.get("has_index_card", False)
                card_badge = "✅ Indexed" if has_card else "⬜ Not indexed"
                src_label = f"`{src.get('label', s_id)}`  {card_badge}  — {src.get('title', '')}"

                with st.expander(src_label, expanded=False):
                    sc1, sc2, sc3 = st.columns([4, 1, 1])
                    with sc2:
                        if st.button("✏️ Edit", key=f"edit_src_btn_{s_id}"):
                             st.session_state[f"editing_src_{s_id}"] = True
                    with sc3:
                        if st.button("🗑️ Delete", key=f"del_src_{s_id}"):
                            api.delete_source(g_id, s_id)
                            st.rerun()

                    if st.session_state.get(f"editing_src_{s_id}"):
                        with st.form(f"edit_src_form_{s_id}"):
                            st.markdown("**Edit Document**")
                            se1, se2 = st.columns(2)
                            with se1:
                                e_lbl = st.text_input("Label", value=src.get("label", ""))
                                e_pages = st.text_input("Page Range", value=src.get("page_range", "") or "")
                            with se2:
                                e_stitle = st.text_input("Title", value=src.get("title", ""))
                                e_file = st.text_input("File name", value=src.get("file_name", "") or "")
                            sb1, sb2 = st.columns(2)
                            with sb1:
                                if st.form_submit_button("Save", use_container_width=True, type="primary"):
                                    api.update_source(g_id, s_id, {
                                        "label": e_lbl or None,
                                        "title": e_stitle or None,
                                        "page_range": e_pages or None,
                                        "file_name": e_file or None,
                                    })
                                    st.session_state[f"editing_src_{s_id}"] = False
                                    ui.success("Source updated.")
                                    st.rerun()
                            with sb2:
                                if st.form_submit_button("Cancel", use_container_width=True):
                                    st.session_state[f"editing_src_{s_id}"] = False
                                    st.rerun()

                    source_notes = notes_data.get("source", {}).get(s_id, [])
                    _render_notes_section("source", s_id, f"src_{s_id}", source_notes)

                    st.divider()
                    st.markdown("**Index Card**")
                    st.caption("Structured summary injected into compiled prompts.")
                    embedded_card = src.get("index_card")
                    _render_index_card_form(g_id, s_id, has_card, embedded_card)# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — ADD SOURCE GROUP (existing import tab + manual form)
# ══════════════════════════════════════════════════════════════════════════════

st.subheader("📥 Add Source Group")

tab_import, tab_manual = st.tabs([
    "📥 Import source.json  *(batch)*",
    "✏️ Register manually"
])

with tab_import:
    from import_fixer import render_source_import_tab
    render_source_import_tab()

with tab_manual:
    st.caption("Use this to register a work field-by-field, or to patch metadata after a JSON import.")
    with st.form("new_group_form"):
        col1, col2, col3 = st.columns([3, 2, 1])
        with col1:
            g_title = st.text_input("Title of the Work")
            g_author = st.text_input("Author(s)")
        with col2:
            g_type = st.selectbox("Type", SOURCE_TYPES)
            g_inst = st.text_input("Institution / Publisher", placeholder="e.g. JNU, OUP")
        with col3:
            g_year = st.number_input("Year", min_value=1800, max_value=2100, value=2020, step=1)

        g_desc = st.text_area(
            "Why are you using this work?",
            height=80,
            placeholder="e.g. Primary source for Chapter 1 historical background."
        )
        if st.form_submit_button("Register Work", use_container_width=True, type="primary"):
            if not g_title or not g_author:
                st.error("Title and Author are required.")
            else:
                result = api.create_source_group({
                    "title": g_title, "author": g_author, "year": int(g_year),
                    "source_type": g_type, "institution_or_publisher": g_inst or None,
                    "description": g_desc or None,
                })
                if result:
                    ui.success(f"Registered: {g_title}")
                    st.rerun()

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — Register Drive Links
# Scan local folder → display thesis folders → paste JSON → save + import
# ══════════════════════════════════════════════════════════════════════════════

st.subheader("🗂️ Register Drive Links Here")
st.caption(
    "Scan your local thesis folder. For each thesis: copy the file list, "
    "upload to NotebookLM, paste the JSON output back here, save and import."
)

# ── Path config + scan button ──────────────────────────────────────────────────

col_path, col_scan = st.columns([4, 1])
with col_path:
    # Default path pre-filled — user can change it
    root_path = st.text_input(
        "Parent folder path",
        value=st.session_state.get("scan_root_path", r"C:\Users\TUSHAR\Downloads\Shodhganga_Downloads"),
        placeholder=r"C:\Users\TUSHAR\Downloads\Shodhganga_Downloads",
        label_visibility="collapsed"
    )
with col_scan:
    scan_clicked = st.button("🔍 Scan Folder", use_container_width=True, type="primary")

if scan_clicked and root_path.strip():
    st.session_state["scan_root_path"] = root_path.strip()
    with st.spinner("Scanning..."):
        result = api.scan_local_folder(root_path.strip())
    if result:
        st.session_state["scan_result"] = result
        newly = result.get("newly_added", 0)
        total = result.get("total_thesis_folders", 0)
        if newly > 0:
            ui.success(f"Scan complete. {newly} new thesis folders added. {total} total.")
        else:
            ui.success(f"Scan complete. No new folders found. {total} total.")

# ── Row 2: Drive link registration — one call registers all thesis folders ─────
col_drive, col_reg = st.columns([4, 1])
with col_drive:
    drive_parent_id = st.text_input(
        "Google Drive parent folder ID",
        value=st.session_state.get("drive_parent_id", ""),
        placeholder="Paste Drive parent folder ID — e.g. 1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs",
        label_visibility="collapsed",
        help=(
            "Open your parent thesis folder on Google Drive. "
            "The folder ID is the last part of the URL: "
            "drive.google.com/drive/folders/FOLDER_ID_HERE. "
            "The folder must be shared as 'Anyone with the link → Viewer'."
        )
    )
with col_reg:
    reg_clicked = st.button("🔗 Register Drive Links", use_container_width=True)

if reg_clicked:
    if not drive_parent_id.strip():
        st.error("Paste the Drive parent folder ID first.")
    else:
        st.session_state["drive_parent_id"] = drive_parent_id.strip()
        with st.spinner("Walking Drive folder tree and registering links..."):
            reg_result = api.register_drive_links(drive_parent_id.strip())
        if reg_result:
            n_reg = reg_result.get("registered_count", 0)
            n_skip = reg_result.get("skipped_count", 0)
            if n_reg > 0:
                ui.success(f"Registered Drive links for {n_reg} thesis folders.")
            if n_skip > 0:
                with st.expander(f"⚠️ {n_skip} folders skipped — click to see why"):
                    for s in reg_result.get("skipped", []):
                        st.caption(f"• **{s['folder']}** — {s['reason']}")
            st.rerun()

# ── Load and display thesis folders ───────────────────────────────────────────

thesis_data = api.get_local_files()
thesis_folders = thesis_data.get("thesis_folders", []) if thesis_data else []

if thesis_folders:
    st.markdown(f"**{len(thesis_folders)} thesis folders found:**")

    for entry in thesis_folders:
        thesis_name = entry["thesis_name"]
        files = entry.get("files", [])
        imported = entry.get("imported", False)
        import_error = entry.get("import_error")

        # Build expander label with status badge
        if imported:
            badge = "✅ Imported"
        elif import_error:
            badge = "❌ Import failed"
        else:
            badge = "⬜ Not imported"

        drive_registered = entry.get("drive_links_registered", False)
        drive_badge = "🔗 Drive linked" if drive_registered else "☁️ Drive not linked"
        expander_label = f"**{thesis_name}**  ·  {len(files)} PDFs  ·  {badge}  ·  {drive_badge}"

        with st.expander(expander_label, expanded=False):

            # ── File list ──────────────────────────────────────────────────────
            if files:
                st.markdown("**PDFs in this folder:**")

                # If Drive links are registered, show them as clickable links
                # alongside filenames so user can copy individual links too
                if drive_registered:
                    drive_links_data = api.get_drive_links(thesis_name) or {}
                    links_dict = drive_links_data.get("links", {})

                    all_drive_links = []
                    for fname in files:
                        link = links_dict.get(fname)
                        if link:
                            st.markdown(f"  • [`{fname}`]({link})")
                            all_drive_links.append(link)
                        else:
                            # File exists locally but not found in Drive scan
                            st.markdown(f"  • `{fname}`  ⚠️ *not found in Drive*")

                    if all_drive_links:
                        st.markdown("**Copy all Drive links (paste into NotebookLM Add Source):**")
                        st.code("\n".join(all_drive_links), language=None)
                        st.caption("☝️ Copy the links above and paste into NotebookLM's Add Source dialog.")
                else:
                    # No Drive links yet — show plain filenames
                    file_list_text = "\n".join(files)
                    st.code(file_list_text, language=None)
                    st.caption("☝️ Copy filenames above to upload manually. Register Drive links below for direct URLs.")
            else:
                st.warning("No PDF files found in this folder.")

            st.divider()

            # ── Show existing import status ────────────────────────────────────
            if imported:
                group_id = entry.get("import_group_id")
                imported_at = entry.get("imported_at", "")[:19].replace("T", " ") if entry.get("imported_at") else "?"
                st.success(f"Imported at {imported_at}. Group ID: `{group_id}`")

            if import_error:
                st.error(f"Last import error: {import_error}")
                st.caption("Fix the JSON and re-import manually from the import tab below.")

            # ── JSON paste + save ──────────────────────────────────────────────
            st.markdown("**Paste NotebookLM JSON output:**")
            st.caption(
                "Upload the PDFs listed above to NotebookLM, run the extraction prompt, "
                "then paste the JSON response here."
            )

            json_input = st.text_area(
                "NotebookLM JSON",
                height=200,
                key=f"json_paste_{thesis_name}",
                placeholder='{\n  "title": "...",\n  "author": "...",\n  "chapters": [...]\n}',
                label_visibility="collapsed"
            )

            save_col, _ = st.columns([1, 2])
            with save_col:
                save_clicked = st.button(
                    "💾 Save JSON + Import",
                    key=f"save_btn_{thesis_name}",
                    use_container_width=True,
                    type="primary"
                )

            if save_clicked:
                if not json_input.strip():
                    st.error("Paste the JSON output first.")
                else:
                    with st.spinner("Saving and importing..."):
                        result = api.save_index_card_json(
                            thesis_name=thesis_name,
                            level2_path=entry["level2_path"],
                            json_text=json_input.strip()
                        )
                    if result:
                        if result.get("imported"):
                            sources_n = result.get("sources_created", 0)
                            ui.success(
                                f"✅ Saved to `{result.get('json_path', '')}` · "
                                f"Imported {sources_n} sources."
                            )
                        else:
                            st.warning(
                                f"JSON saved to `{result.get('json_path', '')}` but import failed: "
                                f"{result.get('import_error', 'unknown error')}. "
                                "Re-import manually from the tab below."
                            )
                        st.rerun()

elif not scan_clicked:
    st.info("Enter your parent folder path above and click **Scan Folder** to get started.")

st.divider()

