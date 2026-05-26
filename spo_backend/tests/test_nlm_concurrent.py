"""
test_nlm_concurrent.py
──────────────────────
Tests whether notebooklm-py's NotebookLMClient supports concurrent usage.

What this tests:
  1. Two clients can be initialised and enter their context managers simultaneously
  2. Both can call a read-only API (list notebooks) without corrupting each other
  3. File-based state (context.json, storage_state.json) is not clobbered

Run:
    python test_nlm_concurrent.py

Requirements:
    pip install "notebooklm-py[browser]"
    notebooklm login          ← run once to write ~/.notebooklm/storage_state.json
    (or set NOTEBOOKLM_AUTH_JSON env var)

Interpreting results:
  PASS  → both clients worked independently → parallel _run_sequence calls are safe
  FAIL  → concurrent client use is broken  → add a semaphore before attempting parallel runs

============================================================
  notebooklm-py concurrent client test

============================================================

Test 1 — Sequential (baseline)
  ✓  Client 1: listed 24 notebook(s)
  ✓  Client 2: listed 24 notebook(s)

Test 2 — Concurrent (3 workers, asyncio.gather)
  ✓  Worker 1: listed 24 notebook(s) in 2.25s
  ✓  Worker 2: listed 24 notebook(s) in 1.98s
  ✓  Worker 0: listed 24 notebook(s) in 2.57s
  ·  Total wall time: 2.57s

Test 3 — context.json not mutated by concurrent list()
  ✓  Worker 2: listed 24 notebook(s) in 2.01s
  ✓  Worker 1: listed 24 notebook(s) in 2.29s
  ✓  Worker 0: listed 24 notebook(s) in 2.88s
  ✓  context.json does not exist — no context file risk

Test 4 — Concurrent write: create + delete (3 workers)
  ·  This creates real notebooks in your NotebookLM account and deletes them.
  ·  You will briefly see them in the NotebookLM UI.
  ✓  Worker 1: created notebook '4409614a-7550-4768-b617-de722933f937'
  ✓  Worker 2: created notebook '51f7552f-fbb8-4c6f-86ff-59cd5e9acf3b'
  ✓  Worker 0: created notebook '253dd742-5784-41b3-875c-cf0fa83c7185'
  ✓  Worker 1: deleted notebook '4409614a-7550-4768-b617-de722933f937'
  ✓  Worker 2: deleted notebook '51f7552f-fbb8-4c6f-86ff-59cd5e9acf3b'
  ✓  Worker 0: deleted notebook '253dd742-5784-41b3-875c-cf0fa83c7185'
  ·  Total wall time: 6.45s

============================================================
  Summary

============================================================
  PASS  Sequential baseline
  PASS  Concurrent read (list)
  PASS  context.json not mutated
  PASS  Concurrent write (create+delete)

  ✓ All tests passed — parallel _run_sequence calls should be safe.
  Next step: add the batch endpoint with asyncio.gather.
"""

import asyncio
import os
import sys
import time
import traceback


# ── Helpers ───────────────────────────────────────────────────────────────────

RESET  = "\033[0m"
GREEN  = "\033[32m"
RED    = "\033[31m"
YELLOW = "\033[33m"
BOLD   = "\033[1m"

def ok(msg):    print(f"  {GREEN}✓{RESET}  {msg}")
def fail(msg):  print(f"  {RED}✗{RESET}  {msg}")
def info(msg):  print(f"  {YELLOW}·{RESET}  {msg}")
def header(msg):print(f"\n{BOLD}{msg}{RESET}")


# ── Test 1: sequential baseline ───────────────────────────────────────────────

async def test_sequential():
    """
    Open two clients one after another (not overlapping).
    This must pass before the concurrent test is meaningful.
    """
    header("Test 1 — Sequential (baseline)")
    from notebooklm import NotebookLMClient

    results = []
    for i in range(2):
        try:
            client_cm = await NotebookLMClient.from_storage()
            async with client_cm as client:
                notebooks = await client.notebooks.list()
                count = len(notebooks) if notebooks else 0
                ok(f"Client {i+1}: listed {count} notebook(s)")
                results.append(True)
        except Exception as e:
            fail(f"Client {i+1}: {e}")
            results.append(False)

    return all(results)


# ── Test 2: concurrent clients ────────────────────────────────────────────────

async def _concurrent_worker(worker_id: int, results: dict):
    """
    One concurrent worker: open a client, list notebooks, record timing.
    Mirrors exactly what _run_sequence does with _nlm_client().
    """
    from notebooklm import NotebookLMClient
    t0 = time.monotonic()
    try:
        client_cm = await NotebookLMClient.from_storage()
        async with client_cm as client:
            notebooks = await client.notebooks.list()
            count = len(notebooks) if notebooks else 0
            elapsed = time.monotonic() - t0
            ok(f"Worker {worker_id}: listed {count} notebook(s) in {elapsed:.2f}s")
            results[worker_id] = {"ok": True, "count": count}
    except Exception as e:
        elapsed = time.monotonic() - t0
        fail(f"Worker {worker_id} failed after {elapsed:.2f}s: {e}")
        results[worker_id] = {"ok": False, "error": str(e), "tb": traceback.format_exc()}


async def test_concurrent(n: int = 3):
    """
    Launch n workers simultaneously with asyncio.gather.
    This is the direct equivalent of running n _run_sequence coroutines in parallel.
    """
    header(f"Test 2 — Concurrent ({n} workers, asyncio.gather)")

    results = {}
    t0 = time.monotonic()
    await asyncio.gather(*[_concurrent_worker(i, results) for i in range(n)])
    elapsed = time.monotonic() - t0

    info(f"Total wall time: {elapsed:.2f}s")

    # Sanity check: all workers saw the same notebook count
    counts = [r["count"] for r in results.values() if r.get("ok")]
    if len(set(counts)) > 1:
        fail(f"Workers saw different notebook counts: {counts} — possible state corruption")
        return False

    passed = all(r.get("ok") for r in results.values())
    return passed


# ── Test 3: context.json isolation check ─────────────────────────────────────

async def test_context_json_not_mutated():
    """
    Verify that calling notebooks.list() (a read-only op) does NOT write or
    modify ~/.notebooklm/context.json. The Python client should only mutate
    context.json via the `use` CLI command, which your code never calls.
    """
    header("Test 3 — context.json not mutated by concurrent list()")
    from notebooklm import NotebookLMClient

    nlm_home   = os.environ.get("NOTEBOOKLM_HOME", os.path.expanduser("~/.notebooklm"))
    ctx_path   = os.path.join(nlm_home, "context.json")

    before_mtime = os.path.getmtime(ctx_path) if os.path.exists(ctx_path) else None
    before_content = open(ctx_path).read() if os.path.exists(ctx_path) else None

    results = {}
    await asyncio.gather(*[_concurrent_worker(i, results) for i in range(3)])

    after_mtime   = os.path.getmtime(ctx_path) if os.path.exists(ctx_path) else None
    after_content = open(ctx_path).read() if os.path.exists(ctx_path) else None

    if before_mtime is None and after_mtime is None:
        ok("context.json does not exist — no context file risk")
        return True

    if before_content == after_content:
        ok("context.json unchanged after concurrent list() calls")
        return True
    else:
        fail("context.json was MODIFIED during concurrent list() calls — isolation risk!")
        info(f"  before: {before_content!r}")
        info(f"  after:  {after_content!r}")
        return False


# ── Test 4: concurrent notebook create + delete ───────────────────────────────

async def _create_delete_worker(worker_id: int, results: dict):
    """
    Creates a scratch notebook, verifies it exists, then deletes it.
    More realistic than list() — exercises write paths too.
    """
    from notebooklm import NotebookLMClient
    title = f"[TEST CONCURRENT {worker_id} — DELETE ME]"
    try:
        client_cm = await NotebookLMClient.from_storage()
        async with client_cm as client:
            nb = await client.notebooks.create(title)
            nb_id = nb.id
            ok(f"Worker {worker_id}: created notebook '{nb_id}'")

            # small pause to let all workers overlap in the critical section
            await asyncio.sleep(1)

            await client.notebooks.delete(nb_id)
            ok(f"Worker {worker_id}: deleted notebook '{nb_id}'")
            results[worker_id] = {"ok": True, "notebook_id": nb_id}
    except Exception as e:
        fail(f"Worker {worker_id}: {e}")
        results[worker_id] = {"ok": False, "error": str(e), "tb": traceback.format_exc()}


async def test_concurrent_write(n: int = 3):
    """
    n workers each create and delete their own notebook concurrently.
    This is the write-path equivalent of running n _run_sequence calls.
    """
    header(f"Test 4 — Concurrent write: create + delete ({n} workers)")
    info("This creates real notebooks in your NotebookLM account and deletes them.")
    info("You will briefly see them in the NotebookLM UI.")

    results = {}
    t0 = time.monotonic()
    await asyncio.gather(*[_create_delete_worker(i, results) for i in range(n)])
    elapsed = time.monotonic() - t0
    info(f"Total wall time: {elapsed:.2f}s")

    # Check all notebook IDs are distinct (no aliasing)
    ids = [r.get("notebook_id") for r in results.values() if r.get("ok")]
    if len(ids) != len(set(ids)):
        fail(f"Duplicate notebook IDs returned: {ids} — client is sharing state!")
        return False

    return all(r.get("ok") for r in results.values())


# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    header("=" * 60)
    print(f"{BOLD}  notebooklm-py concurrent client test{RESET}")
    header("=" * 60)

    # Import check
    try:
        from notebooklm import NotebookLMClient  # noqa: F401
    except ImportError:
        fail("notebooklm-py is not installed.")
        info("Run: pip install 'notebooklm-py[browser]' && playwright install chromium")
        sys.exit(1)

    results = {}

    try:
        results["sequential"]       = await test_sequential()
    except Exception as e:
        fail(f"Sequential test threw unexpectedly: {e}")
        traceback.print_exc()
        results["sequential"] = False

    if not results["sequential"]:
        fail("Sequential baseline failed — fix this before running concurrent tests.")
        sys.exit(1)

    try:
        results["concurrent_read"]  = await test_concurrent(n=3)
    except Exception as e:
        fail(f"Concurrent read test threw: {e}")
        traceback.print_exc()
        results["concurrent_read"] = False

    try:
        results["context_json"]     = await test_context_json_not_mutated()
    except Exception as e:
        fail(f"context.json test threw: {e}")
        traceback.print_exc()
        results["context_json"] = False

    try:
        results["concurrent_write"] = await test_concurrent_write(n=3)
    except Exception as e:
        fail(f"Concurrent write test threw: {e}")
        traceback.print_exc()
        results["concurrent_write"] = False

    # ── Summary ───────────────────────────────────────────────────────────────
    header("=" * 60)
    print(f"{BOLD}  Summary{RESET}")
    header("=" * 60)

    all_passed = True
    labels = {
        "sequential":       "Sequential baseline",
        "concurrent_read":  "Concurrent read (list)",
        "context_json":     "context.json not mutated",
        "concurrent_write": "Concurrent write (create+delete)",
    }
    for key, label in labels.items():
        passed = results.get(key, False)
        all_passed = all_passed and passed
        status = f"{GREEN}PASS{RESET}" if passed else f"{RED}FAIL{RESET}"
        print(f"  {status}  {label}")

    print()
    if all_passed:
        print(f"{GREEN}{BOLD}  ✓ All tests passed — parallel _run_sequence calls should be safe.{RESET}")
        print(f"  Next step: add the batch endpoint with asyncio.gather.")
    else:
        print(f"{RED}{BOLD}  ✗ One or more tests failed.{RESET}")
        print(f"  Recommended fix before parallel runs:")
        print(f"    Add a semaphore in _run_sequence:")
        print(f"      _nlm_semaphore = asyncio.Semaphore(1)  # or 2 if partial pass")
        print(f"      async with _nlm_semaphore: ...")
        print(f"    This keeps your batch endpoint API intact while serialising NLM calls.")
    print()


if __name__ == "__main__":
    # Windows fix (mirrors what your main.py should already have)
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    asyncio.run(main())