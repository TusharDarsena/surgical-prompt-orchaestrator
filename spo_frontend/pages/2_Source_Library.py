"""
Page: Source Library
Manage external sources — groups, individual PDFs, index cards, and notes.
"""

import json
import streamlit as st
import api
import ui

st.set_page_config(page_title="Source Library · SPO", page_icon="📖", layout="wide")
ui.page_header("📖 Source Library", "Register sources, write index cards, and paste raw reading notes.")

SOURCE_TYPES = ["thesis_chapter", "book_chapter", "journal_article", "book", "report", "other"]


# ══════════════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS — defined first, before any rendering loop
# ══════════════════════════════════════════════════════════════════════════════

def _render_notes_section(scope: str, entity_id: str, key_prefix: str):
    notes = api.list_notes(scope, entity_id)
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


def _render_index_card_form(group_id: str, source_id: str, has_card: bool):
    existing = api.get_index_card(group_id, source_id) if has_card else None

    with st.form(f"card_form_{source_id}"):
        default_claims = "\n".join(existing.get("key_claims", [])) if existing else ""
        claims_raw = st.text_area(
            "Key Claims ★  (one per line)",
            value=default_claims,
            height=150,
            help="2–5 specific claims this source makes. These go directly into the Architect prompt.",
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
            help="Feeds the 'Do Not Include' section of Task.md."
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
# ADD SOURCE GROUP — two paths: JSON import (recommended) or manual form
# ══════════════════════════════════════════════════════════════════════════════

tab_import, tab_manual = st.tabs([
    "📥 Import source.json  *(recommended)*",
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
# SOURCE GROUPS LIST
# ══════════════════════════════════════════════════════════════════════════════

groups = api.list_source_groups()

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

        # Inline group edit form
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

        _render_notes_section("source_group", g_id, f"grp_{g_id}")

        st.divider()

        # ── Add source ─────────────────────────────────────────────────────────
        sources = api.list_sources(g_id)

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

        # ── Sources list ───────────────────────────────────────────────────────
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

                    # Inline source edit form
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

                    _render_notes_section("source", s_id, f"src_{s_id}")

                    st.divider()
                    st.markdown("**Index Card**")
                    st.caption("Structured summary injected into Architect Mega-Prompts.")
                    _render_index_card_form(g_id, s_id, has_card)