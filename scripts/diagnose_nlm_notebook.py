"""
diagnose_nlm_notebook.py
------------------------
Diagnoses the NotebookLM state for a specific chapter and subtopic.
It verifies if the notebook ID stored in the local state still exists
on NotebookLM and checks the status of the sources within it.

Usage:
    python scripts/diagnose_nlm_notebook.py <chapter_id> <subtopic_id>

Example:
    python scripts/diagnose_nlm_notebook.py ch1 1_1
"""

import argparse
import asyncio
import os
import sys

from pathlib import Path

# Add spo_backend to sys.path so we can import services
project_root = Path(__file__).parent.parent
backend_dir = project_root / "spo_backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from services import storage

async def main():
    parser = argparse.ArgumentParser(description="Diagnose NotebookLM state.")
    parser.add_argument("chapter_id", help="Chapter ID (e.g., ch1)")
    parser.add_argument("subtopic_id", help="Subtopic ID (e.g., 1_1)")
    args = parser.parse_args()

    chapter_id = args.chapter_id
    subtopic_id = args.subtopic_id

    print(f"=== DIAGNOSING NOTEBOOKLM STATE FOR {chapter_id} / {subtopic_id} ===")
    
    # 1. Read local state
    state = storage.read_nlm_state(chapter_id, subtopic_id)
    if not state:
        print(f"[FAIL] No nlm_state found for {chapter_id} / {subtopic_id}.")
        print("       Run a draft generation first to create state.")
        sys.exit(1)

    print("\n[OK] Found local state:")
    print(f"     Status: {state.get('status')}")
    print(f"     Last Run: {state.get('last_run_at')}")
    print(f"     Run Count: {state.get('run_count')}")
    if state.get("error"):
        print(f"     Error: {state.get('error')}")

    notebook_id = state.get("notebook_id")
    if not notebook_id:
        print("\n[FAIL] No notebook_id found in local state.")
        sys.exit(1)

    print(f"\n[OK] Found notebook_id: {notebook_id}")

    # 2. Check notebooklm-py
    try:
        from notebooklm import NotebookLMClient
    except ImportError:
        print("\n[FAIL] notebooklm-py is not installed.")
        sys.exit(1)

    # 3. Verify on NotebookLM
    print(f"\n=== VERIFYING ON NOTEBOOKLM ===")
    try:
        async with await NotebookLMClient.from_storage() as client:
            print("[OK] Authenticated with NotebookLM.")
            
            # Check notebook
            try:
                nb = await client.notebooks.get(notebook_id)
                print(f"[OK] Notebook exists: '{nb.title}'")
            except Exception as e:
                print(f"[FAIL] Notebook could not be fetched. Error: {e}")
                print("       Diagnosis: The notebook was likely deleted. The backend will recreate it on the next run.")
                sys.exit(1)

            # Check sources
            try:
                sources = await client.sources.list(notebook_id)
                print(f"\n[OK] Found {len(sources)} sources in notebook:")
                for s in sources:
                    print(f"     - {s.title} (ID: {s.id})")
                
                if len(sources) >= 50:
                    print("\n[WARN] Notebook has reached the 50 sources limit! Further uploads will fail.")
            except Exception as e:
                print(f"[FAIL] Could not list sources. Error: {e}")

    except Exception as e:
        print(f"\n[FAIL] NotebookLMClient initialization failed: {e}")
        sys.exit(1)

    print("\n=== DIAGNOSIS COMPLETE ===")
    print("[PASS] The notebook and its sources are healthy and accessible.")

if __name__ == "__main__":
    asyncio.run(main())
