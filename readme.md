# SPO — Surgical Prompt Orchestrator 🎯

A personal academic writing tool. Not an AI. A **prompt stitching engine**.

SPO bridges the gap between your research sources and your structural writing. It ensures that Claude and NotebookLM "see" your thesis's master argument, your chapter goals, and your hand-curated evidence in every single interaction.

---

## 🚀 The Core Workflow

Every subtopic in your thesis follows this precise sequence:

### 1. The Architect Phase (Claude)
- **Compile:** SPO gathers your synopsis, chapter arc, relevant source index cards, and the summary of your previous section.
- **Prompt:** You paste the "Architect Prompt" into Claude.
- **Output:** Claude provides a `Task.md`—a detailed structural blueprint for the section.
- **Refine:** You edit `Task.md` to ensure the logic and citations are perfect.

### 2. The Writing Phase (NotebookLM)
- **Prompt:** SPO generates a "Writing Prompt" based on your approved `Task.md` and style rules.
- **Generate:** You paste this into NotebookLM (grounded in your source PDFs).
- **Output:** NotebookLM writes the actual draft, strictly following your blueprint and using only your provided sources.

### 3. The Consistency Phase
- **Save:** You save a summary of what was argued in this section.
- **Flow:** This summary is automatically injected into the *next* section's prompt as "Previous Section Context," maintaining a perfect argumentative chain.

---

## 🛠️ Setup

### Prerequisites
- Python 3.10+
- Source PDFs (to be uploaded to NotebookLM)

### Installation
1. Clone the repository.
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Start the Backend:
   ```bash
   uvicorn spo_backend.main:app --reload --port 8000
   ```
4. Access the UI:
   - Modern UI: [http://localhost:8000/app](http://localhost:8000/app)
   - API Docs: [http://localhost:8000/docs](http://localhost:8000/docs)

---

## 📚 Writing Guides

### Index Cards vs Notes
| | Notes | Index Cards |
|---|---|---|
| **When to write** | While reading; raw impressions. | Before writing the section. |
| **Structure** | None — paste anything. | Structured fields (claims, themes). |
| **LLM Impact** | Internal reference only. | **Injected into prompts.** |
| **Purpose** | Your scratch pad. | Claude's evidence layer. |

### Index Card Quality
The index card is the most important data point in SPO. Claude generates blueprints based *entirely* on your cards.
- **Bad claim:** "Discusses women in Indian literature."
- **Good claim:** "Argues pre-1947 male-authored texts constructed female characters as nationalist symbols, erasing individual agency ('nationalist idealization')."

---

## 🏗️ Technical Documentation

For details on the system design, tech stack, and data persistence layer, see:
👉 **[architecture.md](./architecture.md)**