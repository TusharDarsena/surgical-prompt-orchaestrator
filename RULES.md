# RULES.md — Code Quality Rules

> These rules exist because AI assistants sometimes produce code that looks right but creates long-term mess.
> Every rule here solves a real problem. Follow all of them, always.

---

## The Core Philosophy

**Write code as if a senior developer will review it tomorrow.**
Not a junior who will accept anything that works — a senior who will ask:
- Why is this here?
- What happens when this fails?
- Why is this function 150 lines long?
- Why do we have two functions doing the same thing?

---

## Rule 1 — No Dead Code

**What it means:** If code is not being used, it does not exist in this codebase.

**Applies to:**
- Commented-out functions or blocks
- Imported modules that are never used
- Variables that are declared but never read
- Functions that are defined but never called
- Old implementations left after a rewrite

**What to do:** Delete it. Not comment it. Delete it. Git exists for history.

```js
// ❌ WRONG
// const oldFetchUser = async (id) => { ... }  // keeping just in case

// ✅ RIGHT
// It's gone. If needed later, git history has it.
```

---

## Rule 2 — No Unhandled Errors

**What it means:** Every operation that can fail, must handle failure.

```js
// ❌ WRONG
const data = await fetchUser(id);
return data;

// ✅ RIGHT
try {
  const data = await fetchUser(id);
  return { success: true, data };
} catch (error) {
  console.error('[fetchUser] Failed:', error.message);
  return { success: false, error: error.message };
}
```

**Frontend rule:** Every API call must have a loading state, success state, and error state.

---

## Rule 3 — One Function, One Job

**What it means:** A function should do exactly one thing and do it well.

**Warning signs a function is doing too much:**
- It's longer than 40 lines
- Its name contains "and" — `fetchAndProcessUser()`
- It has more than 3 levels of nesting
- You struggle to describe what it does in one sentence

**What to do:** Break it into smaller functions. Name each one clearly.

```js
// ❌ WRONG
async function handleUserLogin(req, res) {
  // validate + check db + generate token + send email + respond — 80 lines
}

// ✅ RIGHT
async function handleUserLogin(req, res) {
  const validation = validateLoginInput(req.body);
  if (!validation.ok) return res.status(400).json(validation.error);

  const user = await findUserByEmail(req.body.email);
  if (!user) return res.status(404).json({ error: 'User not found' });

  const token = generateAuthToken(user);
  await sendLoginNotification(user.email);

  return res.status(200).json({ token });
}
```

---

## Rule 4 — No Magic Numbers or Hardcoded Strings

```js
// ❌ WRONG
if (user.role === 3) { ... }
setTimeout(fn, 86400000);

// ✅ RIGHT
const ROLE_ADMIN = 3;
const ONE_DAY_MS = 86400000;

if (user.role === ROLE_ADMIN) { ... }
setTimeout(fn, ONE_DAY_MS);
```

Environment-specific values (URLs, ports, secrets) go in `.env`. Never in code.

---

## Rule 5 — No God Files

**What it means:** No single file should try to do everything.

**Limits to watch:**
- Component files: ~150 lines max
- Controller files: ~100 lines max
- Service files: ~200 lines max
- Utility files: ~150 lines max

**When a file grows too large:**
- Split by concern — separate data fetching from rendering
- Extract reusable logic into a hook or utility
- Flag it: `// TODO: This file is getting large, consider splitting`

---

## Rule 6 — Consistent Code Style

**The rule:** Match the existing style of the file you are editing.

Check before writing:
- Single quotes or double quotes?
- Semicolons or no semicolons?
- Arrow functions or function declarations?
- async/await or .then() chains?
- 2-space or 4-space indent?

Pick the style that already exists. Do not mix.

---

## Rule 7 — All API Calls Go Through Services Layer

```js
// ❌ WRONG — fetch inside component
function UserProfile() {
  useEffect(() => {
    fetch('/api/user/1').then(...)
  }, []);
}

// ✅ RIGHT — through service
// /src/services/userService.js
export const getUser = async (id) => {
  const res = await fetch(`/api/user/${id}`);
  return res.json();
};

import { getUser } from '../services/userService';
```

---

## Rule 8 — Leave the Codebase Cleaner Than You Found It

After every task:
- Remove any import you added but didn't use
- Remove any console.log you added for debugging
- Remove any TODO you resolved
- Check the file you edited for obvious dead code nearby

---

## Checklist Before Every Task is Complete

```
[ ] Dead code removed
[ ] Unused imports removed
[ ] Error handling in place (try/catch backend, error state frontend)
[ ] No hardcoded values that belong in .env or constants
[ ] No file exceeds size guidelines
[ ] Style matches existing code in this file
[ ] Only touched files relevant to this task
[ ] No new packages added without permission
```
