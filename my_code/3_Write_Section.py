"""
Page: Write a Section
Direct flow — chapterization data → NotebookLM prompt → write → save draft → save consistency summary.
No intermediate Architect/Task.md step.
"""

import streamlit as st
import api
import ui

st.set_page_config(page_title="Write a Section · SPO", page_icon="✍️", layout="wide")
ui.page_header("✍️ Write a Section", "Compile prompt. Upload PDFs to NotebookLM. Get draft. Save.")

# ── Select chapter + subtopic ──────────────────────────────────────────────────
chapters = api.list_chapters()
chapter_id, chapter, subtopic = ui.subtopic_selector(chapters)

if not subtopic:
    st.stop()

subtopic_id = subtopic["subtopic_id"]

# ── When subtopic changes, clear cached prompt and load saved draft ────────────
# Track which subtopic was last active so we can detect a switch
last_subtopic = st.session_state.get("_last_subtopic_id")
if last_subtopic != subtopic_id:
    # Clear stale prompt from previous subtopic
    st.session_state.pop("nlm_prompt", None)
    st.session_state.pop("nlm_meta", None)
    # Load saved draft for the newly selected subtopic
    draft_data = api.get_section_draft(chapter_id, subtopic_id)
    st.session_state["draft_text"] = draft_data.get("text", "") if draft_data else ""
    st.session_state["_last_subtopic_id"] = subtopic_id

# ── Status bar ─────────────────────────────────────────────────────────────────
prev = api.get_previous_summary(chapter_id, subtopic_id)
source_ids = subtopic.get("source_ids", [])

st.divider()
col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("Source Guidance", f"{len(source_ids)} sources")
with col2:
    est_pages = subtopic.get("estimated_pages")
    st.metric("Est. Pages", est_pages if est_pages else "—")
with col3:
    has_prev = bool(prev.get("summary") if prev else False)
    st.metric("Previous Section", "✅ Found" if has_prev else "— First section")
with col4:
    chain = api.get_chapter_chain(chapter_id)
    st.metric("Sections Done (Ch.)", len(chain))

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SOURCES PANEL
# ══════════════════════════════════════════════════════════════════════════════
st.subheader("NotebookLM Prompt")
st.caption("Compile → Upload PDFs to NotebookLM → Paste prompt → Get draft → Save.")

if not source_ids:
    st.warning(
        f"Subtopic `{subtopic_id}` has no source_ids in its chapterization data. "
        "Re-import the chapterization JSON with source_ids for each subtopic.",
        icon="⚠️"
    )
else:
    # ── Sources expander ───────────────────────────────────────────────────────
    # required_sources comes from meta after compilation.
    # Before compilation, we show the raw source_ids from chapterization.
    # After compilation, meta.required_sources has resolved filenames + drive links.
    nlm_meta = st.session_state.get("nlm_meta", {})
    resolved_sources = nlm_meta.get("required_sources", [])

    with st.expander("📄 Sources for this subtopic", expanded=True):
        st.markdown("**Upload these sources to NotebookLM before pasting the prompt:**")

        if resolved_sources:
            # Post-compilation: show resolved filenames and drive links if available
            all_links = [s["drive_link"] for s in resolved_sources if s.get("drive_link")]
            all_files = [s["file_name"] for s in resolved_sources if s.get("file_name")]

            for s in resolved_sources:
                src_name = s.get("source_id", "Unknown")
                ch_ref = s.get("chapter_id", "")
                guidance = s.get("source_guidance", "")
                file_name = s.get("file_name")
                drive_link = s.get("drive_link")

                label = f"📄 **{src_name}**"
                if ch_ref:
                    label += f"  ·  *{ch_ref}*"
                st.markdown(f"- {label}")

                # File resolution status
                if drive_link:
                    st.markdown(f"   🔗 [{file_name}]({drive_link})")
                elif file_name:
                    st.caption(f"   📁 `{file_name}`")
                else:
                    st.caption("   ⚠️ File not resolved — run Scan Folder on Source Library page")

                if guidance:
                    preview = (guidance[:120] + "...") if len(guidance) > 120 else guidance
                    st.caption(f"   ↳ {preview}")

            st.divider()

            # Copy options — drive links if available, filenames otherwise
            if all_links:
                links_text = "\n".join(all_links)
                st.markdown("**Copy Drive links to paste into NotebookLM:**")
                st.code(links_text, language=None)
                st.caption("☝️ Copy the links above and paste into NotebookLM's Add Source dialog.")
            elif all_files:
                files_text = "\n".join(all_files)
                st.markdown("**Files to upload manually:**")
                st.code(files_text, language=None)
                st.caption("☝️ Upload these files from your local folder to NotebookLM.")

            unresolved = [s for s in resolved_sources if not s.get("file_name")]
            if unresolved:
                st.warning(
                    f"{len(unresolved)} source(s) could not be matched to a file. "
                    "Go to Source Library → Scan Folder to register your thesis directory.",
                    icon="⚠️"
                )

        else:
            # Pre-compilation: show raw chapterization source list
            for s in source_ids:
                src_name = s.get("source_id", "Unknown")
                ch_ref = s.get("chapter_id", "")
                guidance = s.get("source_guidance", "")
                label = f"📄 **{src_name}**"
                if ch_ref:
                    label += f"  ·  *{ch_ref}*"
                st.markdown(f"- {label}")
                if guidance:
                    preview = (guidance[:120] + "...") if len(guidance) > 120 else guidance
                    st.caption(f"   ↳ {preview}")
            st.caption("*Compile the prompt below to resolve filenames and Drive links.*")

    # ── Compile controls ───────────────────────────────────────────────────────
    col_n1, col_n2 = st.columns(2)
    with col_n1:
        default_wc = (subtopic.get("estimated_pages", 0) or 0) * 250
        nlm_wc = st.number_input(
            "Word count target",
            min_value=0, max_value=5000,
            value=default_wc if default_wc > 0 else 800,
            step=100
        )
    with col_n2:
        nlm_style = st.text_input(
            "Style notes (optional)",
            placeholder="e.g. More analytical, less descriptive"
        )

    if st.button("⚙️ Compile NotebookLM Prompt", use_container_width=True, type="primary"):
        with st.spinner("Compiling..."):
            result = api.compile_notebooklm_prompt(
                chapter_id, subtopic_id,
                word_count=int(nlm_wc) if nlm_wc else None,
                style_notes=nlm_style or None
            )
        if result:
            st.session_state["nlm_prompt"] = result.get("prompt", "")
            st.session_state["nlm_meta"] = result.get("meta", {})
            st.rerun()  # rerun so sources expander updates with resolved files

    # ── Prompt output ──────────────────────────────────────────────────────────
    if st.session_state.get("nlm_prompt"):
        nlm_meta = st.session_state.get("nlm_meta", {})

        st.markdown("**NotebookLM Prompt — Copy and paste into NotebookLM:**")
        ui.prompt_output_box(st.session_state["nlm_prompt"], copy_key="copy_nlm")

        # Warnings from meta
        if nlm_meta.get("warnings"):
            for w in nlm_meta["warnings"]:
                st.warning(w, icon="⚠️")

        with st.expander("📋 What was included"):
            st.json({
                "chapter": nlm_meta.get("chapter"),
                "subtopic": nlm_meta.get("subtopic"),
                "previous_section": nlm_meta.get("previous_section"),
                "source_count": nlm_meta.get("source_count"),
                "word_count_target": nlm_meta.get("word_count_target"),
                "required_sources": nlm_meta.get("required_sources"),
            })

    st.divider()

    # ══════════════════════════════════════════════════════════════════════════
    # DRAFT OUTPUT STORAGE
    # ══════════════════════════════════════════════════════════════════════════
    st.subheader("📝 Draft Output")
    st.caption(
        "Paste NotebookLM's response here. Saved per subtopic — switching subtopics "
        "loads the draft for that subtopic automatically."
    )

    draft_text = st.text_area(
        "Draft",
        value=st.session_state.get("draft_text", ""),
        height=400,
        placeholder="Paste NotebookLM's output here after reviewing it...",
        label_visibility="collapsed",
        key="draft_textarea"
    )

    draft_col1, draft_col2, draft_col3 = st.columns([2, 2, 1])

    with draft_col1:
        save_label = "💾 Save Draft" if not st.session_state.get("draft_text") else "💾 Save Updated Draft"
        if st.button(save_label, use_container_width=True, type="primary"):
            if not draft_text.strip():
                st.error("Paste a draft before saving.")
            else:
                result = api.save_section_draft(chapter_id, subtopic_id, draft_text)
                if result:
                    st.session_state["draft_text"] = draft_text
                    ui.success("Draft saved.")

    with draft_col2:
        if st.session_state.get("draft_text"):
            if st.button("🗑️ Clear Draft", use_container_width=True):
                if st.session_state.get("_confirm_clear_draft"):
                    api.delete_section_draft(chapter_id, subtopic_id)
                    st.session_state["draft_text"] = ""
                    st.session_state.pop("_confirm_clear_draft", None)
                    ui.success("Draft cleared.")
                    st.rerun()
                else:
                    st.session_state["_confirm_clear_draft"] = True
                    st.warning("Click Clear Draft again to confirm.")

    with draft_col3:
        if st.session_state.get("draft_text"):
            st.caption(f"✅ Draft saved")

    st.divider()

    # ══════════════════════════════════════════════════════════════════════════
    # CONSISTENCY SUMMARY
    # ══════════════════════════════════════════════════════════════════════════
    st.subheader("Save Consistency Summary")
    st.caption("After approving the draft, save what was argued here. This feeds into the next subtopic.")

    existing_summary = None
    for entry in chain:
        if entry.get("subtopic_id") == subtopic_id:
            existing_summary = entry
            break

    if existing_summary:
        st.success(f"Summary already saved for this subtopic.", icon="✅")
        with st.expander("View saved summary"):
            st.markdown(f"**{existing_summary.get('core_argument_made', '')}**")
            if existing_summary.get("key_terms_established"):
                st.caption(f"Terms: {', '.join(existing_summary['key_terms_established'])}")

    with st.form("consistency_form"):
        core_arg = st.text_area(
            "What was argued in this section? ★",
            height=120,
            value=existing_summary.get("core_argument_made", "") if existing_summary else "",
            placeholder=(
                "2–3 sentences. e.g. Established that pre-1947 male authors systematically "
                "constructed female characters as nationalist symbols using 'nationalist idealization' "
                "(Sharma Ch.2). This creates the baseline from which feminist writing departed."
            ),
            help="Injected as 'Previous Section Context' in the next subtopic's prompts."
        )
        col1, col2 = st.columns(2)
        with col1:
            terms_raw = st.text_input(
                "Key Terms Established (comma-separated)",
                value=", ".join(existing_summary.get("key_terms_established", [])) if existing_summary else "",
                placeholder="nationalist idealization, representational gap"
            )
            sources_used_raw = st.text_input(
                "Sources Used",
                value=", ".join(existing_summary.get("sources_used", [])) if existing_summary else "",
                placeholder="Sharma Ch.2, Nair 1992"
            )
        with col2:
            bridge = st.text_area(
                "Bridge to Next Section (optional)",
                value=existing_summary.get("what_next_section_must_build_on", "") if existing_summary else "",
                height=100,
                placeholder=(
                    "Next section should use 'nationalist idealization' as established baseline "
                    "and show how feminist writers rejected it."
                )
            )

        if st.form_submit_button("Save Summary", use_container_width=True, type="primary"):
            if not core_arg.strip():
                st.error("The argument summary is required.")
            else:
                data = {
                    "subtopic_number": subtopic["number"],
                    "subtopic_title": subtopic["title"],
                    "core_argument_made": core_arg,
                    "key_terms_established": [t.strip() for t in terms_raw.split(",") if t.strip()],
                    "sources_used": [s.strip() for s in sources_used_raw.split(",") if s.strip()],
                    "what_next_section_must_build_on": bridge or None,
                }
                result = api.save_consistency_summary(chapter_id, subtopic_id, data)
                if result:
                    ui.success("Summary saved. The next subtopic will inherit this context.")
                    st.rerun()
