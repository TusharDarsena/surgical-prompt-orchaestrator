/**
 * app_home.js
 *
 * Fetches backend health, synopsis, chapters, and source counts,
 * then renders the thesis card and health indicator.
 * Read-only — no mutations on this page.
 */

const BASE = window.SPO_API_BASE || "http://localhost:8000";

async function _get(path) {
  const res = await fetch(`${BASE}${path}`);
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(res.statusText);
  return res.json();
}

// ── Render health dot ─────────────────────────────────────────────────────────

function renderHealth(online) {
  const dot  = document.getElementById("healthDot");
  const text = document.getElementById("healthText");
  if (online) {
    dot.classList.remove("offline");
    text.textContent = "Backend connected";
  } else {
    dot.classList.add("offline");
    text.textContent = "Backend offline";
  }
}

// ── Render thesis card ────────────────────────────────────────────────────────

function renderThesisCard(synopsis, chapters, readyCount, driveLinked) {
  const container = document.getElementById("thesisCardSlot");

  if (!synopsis) {
    container.innerHTML = `
      <div class="no-thesis-card">
        No thesis set up yet.
        <a href="/thesis-setup">Go to Thesis Setup →</a>
      </div>
    `;
    return;
  }

  const title  = synopsis.title || "Untitled";
  const author = synopsis.researcher || synopsis.author || "";
  const field  = synopsis.field || "";

  const chCount  = chapters.length;
  const subCount = chapters.reduce((n, c) => n + (c.subtopics?.length ?? 0), 0);
  const arcsMissing = chapters.filter(c => !c.chapter_arc).length;

  const chipsHtml = [
    `<span class="chip ${chCount > 0 ? "ok" : "none"}">${chCount} chapter${chCount !== 1 ? "s" : ""}</span>`,
    `<span class="chip ${subCount > 0 ? "ok" : "none"}">${subCount} subtopic${subCount !== 1 ? "s" : ""}</span>`,
    readyCount > 0
      ? `<span class="chip ok">Sources imported</span>`
      : `<span class="chip none">No sources yet</span>`,
    arcsMissing > 0
      ? `<span class="chip warn">${arcsMissing} arc${arcsMissing !== 1 ? "s" : ""} missing</span>`
      : chCount > 0 ? `<span class="chip ok">All arcs set</span>` : "",
    driveLinked
      ? `<span class="chip ok">Drive linked</span>`
      : "",
  ].filter(Boolean).join("");

  container.innerHTML = `
    <div class="thesis-card">
      <div class="thesis-card-label">Active Thesis</div>
      <div class="thesis-title">${_esc(title)}</div>
      <div class="thesis-meta">${_esc(author)}${field ? " · " + _esc(field) : ""}</div>
      <div class="thesis-chips">${chipsHtml}</div>
    </div>
  `;
}

function _esc(s) {
  return String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

// ── Boot ──────────────────────────────────────────────────────────────────────

async function init() {
  // Health check first — fast, drives the dot
  let online = false;
  try {
    const h = await _get("/");
    online = h?.status === "running";
  } catch (_) {}
  renderHealth(online);

  if (!online) return; // no point loading data if backend is down

  // Parallel fetch of synopsis, chapters, source groups
  const [synopsis, chapters, groups, driveFiles] = await Promise.all([
    _get("/thesis/synopsis").catch(() => null),
    _get("/thesis/chapters").catch(() => []),
    _get("/sources/groups").catch(() => []),
    _get("/drive/local-files").catch(() => null),
  ]);

  // Enrich chapters with subtopic data (needed for arc count)
  // The /thesis/chapters endpoint returns summaries without subtopics,
  // so we fetch each full chapter. Use allSettled to tolerate partial failures.
  let fullChapters = chapters || [];
  if (fullChapters.length) {
    const results = await Promise.allSettled(
      fullChapters.map(c => _get(`/thesis/chapters/${c.chapter_id}`))
    );
    fullChapters = results
      .filter(r => r.status === "fulfilled" && r.value)
      .map(r => r.value);
  }

  // Count indexed sources
  const readyCount = (groups || []).reduce((n, g) => n + (g.ready_count ?? 0), 0);

  // Drive linked = at least one thesis folder has drive_linked === true
  const driveLinked = driveFiles?.folders?.some(f => f.drive_linked) ?? false;

  renderThesisCard(synopsis, fullChapters, readyCount, driveLinked);
}

document.addEventListener("DOMContentLoaded", init);
