"""
SPO — Surgical Prompt Orchestrator
Streamlit frontend entry point.

Run from the spo_frontend directory:
    streamlit run app.py
"""

import streamlit as st
import api

st.set_page_config(
    page_title="SPO — Surgical Prompt Orchestrator",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Backend connection check ───────────────────────────────────────────────────
health = api.health()

with st.sidebar:
    st.markdown("## 🎯 SPO")
    st.caption("Surgical Prompt Orchestrator")
    st.divider()

    if health:
        st.success("Backend connected", icon="🟢")
        st.caption(f"Data: `{health.get('data_dir', '...')}`")
    else:
        st.error("Backend offline", icon="🔴")
        st.caption("Start with: `uvicorn main:app --reload --port 8000`")

    st.divider()
    st.caption("**Workflow**")
    st.caption("1️⃣  Thesis Setup")
    st.caption("2️⃣  Source Library")
    st.caption("3️⃣  Write a Section")
    st.caption("4️⃣  Consistency Chain")

# ── Home page ──────────────────────────────────────────────────────────────────
st.title("🎯 Surgical Prompt Orchestrator")
st.caption("A prompt stitching engine for academic writing.")
st.divider()

synopsis = api.get_synopsis()
chapters = api.list_chapters()

col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric("Thesis Synopsis", "✅ Set" if synopsis else "❌ Missing")

with col2:
    st.metric("Chapters", len(chapters))

with col3:
    subtopic_count = sum(len(c.get("subtopics", [])) for c in chapters)
    st.metric("Subtopics", subtopic_count)

with col4:
    groups = api.list_source_groups()
    ready = sum(g.get("ready_count", 0) for g in groups)
    st.metric("Sources with Index Cards", ready)

st.divider()

# ── Quick status ───────────────────────────────────────────────────────────────
if not synopsis:
    st.warning("**Start here:** Go to **Thesis Setup** and add your synopsis.", icon="👆")
elif not chapters:
    st.warning("**Next:** Add your chapters and subtopics in **Thesis Setup**.", icon="👆")
elif ready == 0:
    st.warning("**Next:** Add sources and write index cards in **Source Library**.", icon="👆")
else:
    st.success(
        f"Ready to write. Go to **Write a Section** to compile prompts.",
        icon="✍️"
    )

if synopsis:
    st.subheader("Your Thesis")
    st.markdown(f"**{synopsis.get('title', '')}**")
    st.markdown(f"*{synopsis.get('author', '')} · {synopsis.get('field', '')}*")
    st.markdown(synopsis.get("central_argument", ""))

st.divider()
st.caption("Navigate using the **pages** in the left sidebar.")
