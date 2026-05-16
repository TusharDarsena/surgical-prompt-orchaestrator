# AGENTS.md — Project Intelligence File

---


### Who You Are Working With

You are assisting a developer who:
- Builds Node.js backends and React frontends
- Designs in Stitch, converts to React using an AI IDE
- Wires frontend to real backend APIs (no permanent dummy data)
- Maintains this codebase with AI assistance across multiple sessions
- Prefers short focused tasks — one task per chat session

---

### Stack

- **Backend:** Python FastAPI
- **Frontend:** Streamlit (Legacy) / Jinja2 (Modern)
- **Database:** Local JSON files (Flat-file)
- **Auth:** None
- **Styling:** Vanilla CSS / HTML5
- **Package manager:** pip

> Fill in the stack before starting any task. Do not assume.

---

### Folder Structure

Expected structure:
```
/
├── spo_backend/            # Core Logic & API (FastAPI)
│   ├── models/             # Pydantic data schemas
│   ├── routers/            # API endpoints
│   ├── services/           # Business logic (Storage, Compiler, etc.)
│   └── main.py             # Entry point
├── spo_frontend/           # Frontend Assets & Pages
│   ├── templates/          # HTML templates (Jinja2)
│   ├── static/             # CSS, JS, and Images
│   └── app.py              # Streamlit entry point (Legacy)
├── docs/                   # Feature documentation & API references
├── AGENTS.md               # Project intelligence file
├── RULES.md                # Code quality rules
└── .env.example
```

> If the actual structure differs, respect what exists. Do not reorganize unless asked.

---

### Naming Conventions

| Type                | Convention                  | Example             |
| ------------------- | --------------------------- | ------------------- |
| React components    | PascalCase                  | `UserCard.jsx`      |
| Hooks               | camelCase with `use` prefix | `useAuthUser.js`    |
| Services            | camelCase                   | `userService.js`    |
| Backend routes      | kebab-case                  | `/api/user-profile` |
| Backend controllers | camelCase                   | `getUserById`       |
| Constants           | UPPER_SNAKE_CASE            | `MAX_RETRY_COUNT`   |
| Variables/functions | camelCase                   | `fetchUserData`     |

---

### API & Wiring Rules

- All API calls from frontend go through `/frontend/src/services/` only
- Never write fetch or axios calls directly inside components
- Backend routes follow: `METHOD /resource` or `METHOD /resource/:id`
- Always handle success and error states when wiring
- Dummy data is temporary — mark it clearly:

```js
// TODO: Replace with real API call — GET /users
const users = DUMMY_USERS;
```

---

### Response Shape

Every backend error must return:
```json
{ "success": false, "error": "Descriptive message here" }
```

Every backend success must return:
```json
{ "success": true, "data": {} }
```

---

### What You Are Allowed to Touch

- Only modify files directly related to the current task
- If a file outside the task scope needs to change → ask first
- Never touch: `.env`, auth logic, database schema, config files — unless explicitly told to
- Never rename files or folders unless explicitly asked

---

### Things You Must Never Do

- Never install a new npm package without asking first
- Never assume an API endpoint exists — check `/docs` or ask
- Never hardcode secrets, URLs, or environment values
- Never leave placeholder comments like "add logic here" in finished code
- Never refactor unrelated code while doing a task

---