# ── ADD TO main.py alongside the other router registrations ───────────────────

from routers import sections
app.include_router(sections.router)
