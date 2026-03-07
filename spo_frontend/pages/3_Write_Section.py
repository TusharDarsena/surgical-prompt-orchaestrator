"""
Page: Write a Section
Direct flow — chapterization data → NotebookLM prompt → write → save draft → save consistency summary.
No intermediate Architect/Task.md step.
"""

import streamlit as st
import streamlit.components.v1 as components
import api
import ui

def copy_button(text: str, label: str, key: str, btn_type: str = "primary"):
    """Render a self-contained JS clipboard copy button with no extra UI."""
    # Escape backticks and backslashes so the text is safe inside a JS template literal
    safe = text.replace("\\", "\\\\").replace("`", "\\`").replace("$", "\\$")
    components.html(f"""
    <style>
      button.cpbtn {{
        width: 100%;
        padding: 0.45rem 1rem;
        background: {"#ff4b4b" if btn_type == "primary" else "#f0f2f6"};
        color: {"white" if btn_type == "primary" else "#262730"};
        border: none;
        border-radius: 0.5rem;
        font-size: 0.875rem;
        font-weight: 500;
        cursor: pointer;
        font-family: inherit;
        transition: opacity 0.15s;
      }}
      button.cpbtn:hover {{ opacity: 0.85; }}
    </style>
    <button class="cpbtn" onclick="
      navigator.clipboard.writeText(`{safe}`).then(() => {{
        this.textContent = '✅ Copied!';
        setTimeout(() => this.textContent = '{label}', 2000);
      }});
    ">{label}</button>
    """, height=42, scrolling=False)

st.set_page_config(page_title="Write a Section · SPO", page_icon="✍️", layout="wide")

# ── Minimal CSS — layout only, no color overrides ─────────────────────────────
st.markdown("""
<style>
#MainMenu, footer { visibility: hidden; }
.block-container {
    padding-top: 1.2rem !important;
    padding-bottom: 3rem !important;
    max-width: 1400px !important;
}
</style>
""", unsafe_allow_html=True)

ui.page_header("✍️ Write a Section", "Compile prompt → Upload to NotebookLM → Paste draft → Save.")

# ── Select chapter + subtopic ──────────────────────────────────────────────────
chapters = api.list_chapters()
chapter_id, chapter, subtopic = ui.subtopic_selector(chapters)

if not subtopic:
    st.stop()

subtopic_id = subtopic["subtopic_id"]

# ── When subtopic changes, clear cached prompt and load saved draft ────────────
last_subtopic = st.session_state.get("_last_subtopic_id")
if last_subtopic != subtopic_id:
    st.session_state.pop("nlm_prompt", None)
    st.session_state.pop("nlm_prompt_1", None)
    st.session_state.pop("nlm_prompt_2", None)
    st.session_state.pop("nlm_meta", None)
    draft_data = api.get_section_draft(chapter_id, subtopic_id)
    st.session_state["draft_text"] = draft_data.get("text", "") if draft_data else ""
    st.session_state["_last_subtopic_id"] = subtopic_id

# ── Fetch data ─────────────────────────────────────────────────────────────────
prev        = api.get_previous_summary(chapter_id, subtopic_id)
source_ids  = subtopic.get("source_ids", [])
chain       = api.get_chapter_chain(chapter_id)

# ── Status bar ─────────────────────────────────────────────────────────────────
st.divider()
col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("Sources", f"{len(source_ids)}")
with col2:
    est_pages = subtopic.get("estimated_pages")
    st.metric("Est. Pages", est_pages if est_pages else "—")
with col3:
    has_prev = bool(prev.get("summary") if prev else False)
    st.metric("Previous Section", "✅ Found" if has_prev else "— First section")
with col4:
    st.metric("Sections Done (Ch.)", len(chain))
st.divider()

if not source_ids:
    st.warning(
        f"Subtopic `{subtopic_id}` has no source_ids in its chapterization data. "
        "Re-import the chapterization JSON with source_ids for each subtopic.",
        icon="⚠️"
    )
    st.stop()

# ══════════════════════════════════════════════════════════════════════════════
# MAIN LAYOUT — left (prompts + draft) | right (sources)
# ══════════════════════════════════════════════════════════════════════════════
col_main, col_sources = st.columns([2.6, 1], gap="large")

# ─────────────────────────────────────────────────────────────────────────────
# RIGHT COLUMN — Sources
# ─────────────────────────────────────────────────────────────────────────────
with col_sources:
    nlm_meta          = st.session_state.get("nlm_meta", {})
    resolved_sources  = nlm_meta.get("required_sources", [])
    display_sources   = resolved_sources if resolved_sources else source_ids

    all_links = []
    all_files = []
    unresolved_count = 0

    for s in display_sources:
        src_name   = s.get("source_id", "Unknown")
        ch_ref     = s.get("chapter_id", "")
        drive_link = s.get("drive_link", "")
        file_name  = s.get("file_name", "")

        if drive_link:
            all_links.append(drive_link)
        elif file_name:
            all_files.append(file_name)
        else:
            unresolved_count += 1

    resolved_count = len(all_links) + len(all_files)
    st.subheader(f"Sources · {resolved_count}/{len(display_sources)}")

    # Show only sources that have a link or file — skip unresolved silently
    for s in display_sources:
        src_name   = s.get("source_id", "Unknown")
        ch_ref     = s.get("chapter_id", "")
        drive_link = s.get("drive_link", "")
        file_name  = s.get("file_name", "")

        if drive_link:
            line = f"🔗 [{src_name}]({drive_link})"
        elif file_name:
            line = f"📁 **{src_name}**"
        else:
            continue  # hide unresolved — no link, nothing useful to show

        if ch_ref:
            line += f"  ·  `{ch_ref}`"
        st.markdown(line)

    if unresolved_count:
        st.caption(f"⚠️ {unresolved_count} unresolved — scan folder in Source Library.")

    st.markdown("")

    # Copy all links — JS button (no code block)
    if all_links:
        copy_button("\n".join(all_links), "📋 Copy All Links", key="copy_links")
    elif all_files:
        copy_button("\n".join(all_files), "📋 Copy File Names", key="copy_files")
    elif not resolved_sources:
        st.caption("*Compile to resolve Drive links.*")

# ─────────────────────────────────────────────────────────────────────────────
# LEFT COLUMN — Compile config, Prompts, Draft
# ─────────────────────────────────────────────────────────────────────────────
with col_main:

    # ── Compile config ─────────────────────────────────────────────────────────
    st.subheader("NotebookLM Prompt")
    st.caption("Configure and compile. Then copy each prompt to its respective tool.")

    cfg_c1, cfg_c2, cfg_c3 = st.columns([1.2, 2, 1.2])
    with cfg_c1:
        default_wc = (subtopic.get("estimated_pages", 0) or 0) * 250
        nlm_wc = st.number_input(
            "Word count target",
            min_value=0, max_value=5000,
            value=default_wc if default_wc > 0 else 800,
            step=100
        )
    with cfg_c2:
        nlm_style = st.text_input(
            "Style notes (optional)",
            placeholder="e.g. More analytical, less descriptive"
        )
    with cfg_c3:
        st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
        compile_clicked = st.button("⚙️ Compile Prompts", use_container_width=True, type="primary")

    if compile_clicked:
        with st.spinner("Compiling…"):
            result = api.compile_notebooklm_prompt(
                chapter_id, subtopic_id,
                word_count=int(nlm_wc) if nlm_wc else None,
                style_notes=nlm_style or None
            )
        if result:
            st.session_state["nlm_prompt_1"] = result.get("prompt_1", "")
            st.session_state["nlm_prompt_2"] = result.get("prompt_2", "")
            st.session_state["nlm_prompt"]   = result.get("prompt", "")
            st.session_state["nlm_meta"]     = result.get("meta", {})
            st.rerun()

    st.markdown("")

    # ── Prompt dialogs (modals) ────────────────────────────────────────────────
    @st.dialog("Stage 1 — NotebookLM Prompt", width="large")
    def show_prompt_1():
        st.markdown(st.session_state.get("nlm_prompt_1", ""))

    @st.dialog("Stage 2 — Gemini Prompt", width="large")
    def show_prompt_2():
        st.markdown(st.session_state.get("nlm_prompt_2", ""))

    # ── Prompt cards ───────────────────────────────────────────────────────────
    prompt_1 = st.session_state.get("nlm_prompt_1", "")
    prompt_2 = st.session_state.get("nlm_prompt_2", "")
    nlm_meta = st.session_state.get("nlm_meta", {})

    pc1, pc2 = st.columns(2, gap="medium")

    with pc1:
        st.markdown("**Stage 1 — NotebookLM**")
        if prompt_1:
            btn_c1, btn_c2 = st.columns(2)
            with btn_c1:
                copy_button(prompt_1, "📋 Copy to Clipboard", key="copy_p1")
            with btn_c2:
                if st.button("📖 Read Prompt", use_container_width=True, key="read_p1"):
                    show_prompt_1()
        else:
            st.caption("*Compile to generate.*")

    with pc2:
        st.markdown("**Stage 2 — Gemini**")
        if prompt_2:
            btn_c3, btn_c4 = st.columns(2)
            with btn_c3:
                copy_button(prompt_2, "📋 Copy to Clipboard", key="copy_p2")
            with btn_c4:
                if st.button("📖 Read Prompt", use_container_width=True, key="read_p2"):
                    show_prompt_2()
        else:
            st.caption("*Compile to generate.*")

    # Warnings + meta
    if nlm_meta.get("warnings"):
        for w in nlm_meta["warnings"]:
            st.warning(w, icon="⚠️")

    if nlm_meta:
        with st.expander("📋 What was included"):
            st.json({
                "chapter":           nlm_meta.get("chapter"),
                "subtopic":          nlm_meta.get("subtopic"),
                "previous_section":  nlm_meta.get("previous_section"),
                "source_count":      nlm_meta.get("source_count"),
                "word_count_target": nlm_meta.get("word_count_target"),
                "required_sources":  nlm_meta.get("required_sources"),
            })

    st.divider()

    # ── Draft ──────────────────────────────────────────────────────────────────
    has_saved_draft = bool(st.session_state.get("draft_text"))

    draft_h1, draft_h2 = st.columns([3, 1])
    with draft_h1:
        st.subheader("📝 Draft Output")
    with draft_h2:
        if has_saved_draft:
            st.markdown("<div style='padding-top:14px; text-align:right'>✅ Saved</div>", unsafe_allow_html=True)

    st.caption(
        "Paste NotebookLM's response here. "
        "Switching subtopics auto-loads the saved draft for that subtopic."
    )

    draft_text = st.text_area(
        "Draft",
        value=st.session_state.get("draft_text", ""),
        height=420,
        placeholder="Paste NotebookLM's output here after reviewing it…",
        label_visibility="collapsed",
        key="draft_textarea"
    )

    wc = len(draft_text.split()) if draft_text.strip() else 0
    st.caption(f"~{wc:,} words")

    draft_col1, draft_col2 = st.columns([3, 2])
    with draft_col1:
        save_label = "💾 Save Updated Draft" if has_saved_draft else "💾 Save Draft"
        if st.button(save_label, use_container_width=True, type="primary"):
            if not draft_text.strip():
                st.error("Paste a draft before saving.")
            else:
                result = api.save_section_draft(chapter_id, subtopic_id, draft_text)
                if result:
                    st.session_state["draft_text"] = draft_text
                    ui.success("Draft saved.")

    with draft_col2:
        if has_saved_draft:
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

# ══════════════════════════════════════════════════════════════════════════════
# CONSISTENCY SUMMARY — full width at bottom
# ══════════════════════════════════════════════════════════════════════════════
st.divider()
st.subheader("🔗 Consistency Summary")
st.caption("After approving the draft, lock in what was argued. This feeds into the next subtopic.")

existing_summary = None
for entry in chain:
    if entry.get("subtopic_id") == subtopic_id:
        existing_summary = entry
        break

if existing_summary:
    st.success("Summary already saved for this subtopic.", icon="✅")
    with st.expander("View saved summary"):
        st.markdown(f"**{existing_summary.get('core_argument_made', '')}**")
        if existing_summary.get("key_terms_established"):
            st.caption(f"Terms: {', '.join(existing_summary['key_terms_established'])}")

with st.form("consistency_form"):
    core_arg = st.text_area(
        "What was argued in this section? ★",
        height=110,
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

    if st.form_submit_button("💾 Save Summary", use_container_width=True, type="primary"):
        if not core_arg.strip():
            st.error("The argument summary is required.")
        else:
            data = {
                "subtopic_number": subtopic["number"],
                "subtopic_title":  subtopic["title"],
                "core_argument_made":              core_arg,
                "key_terms_established":           [t.strip() for t in terms_raw.split(",") if t.strip()],
                "sources_used":                    [s.strip() for s in sources_used_raw.split(",") if s.strip()],
                "what_next_section_must_build_on": bridge or None,
            }
            result = api.save_consistency_summary(chapter_id, subtopic_id, data)
            if result:
                ui.success("Summary saved. The next subtopic will inherit this context.")
                st.rerun()