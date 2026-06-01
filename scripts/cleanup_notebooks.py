import asyncio
import sys
from notebooklm import NotebookLMClient

async def main():
    print("=" * 60)
    print(" NotebookLM Cleanup Utility")
    print("=" * 60)
    print("Connecting to NotebookLM...\n")

    try:
        client_cm = await NotebookLMClient.from_storage()
        async with client_cm as client:
            print("Fetching notebooks...\n")
            notebooks = await client.notebooks.list()
            
            if not notebooks:
                print("No notebooks found.")
                return

            print(f"Found {len(notebooks)} notebooks:\n")
            
            # 1. List all notebooks with index
            for idx, nb in enumerate(notebooks, 1):
                title = nb.title if len(nb.title) <= 70 else nb.title[:67] + "..."
                print(f" [{idx:2}] {title}")
                
            print("\n" + "-" * 60)
            
            # 2. Ask user for exceptions
            print("Which notebooks do you want to KEEP? (These are the exceptions)")
            print("Enter the indices separated by commas (e.g., 1, 4, 17).")
            keep_input = input("Indices to KEEP (leave blank to delete ALL): ").strip()
            
            keep_indices = set()
            if keep_input:
                try:
                    keep_indices = {int(x.strip()) for x in keep_input.split(",") if x.strip()}
                except ValueError:
                    print("\n[ERROR] Invalid input. Please enter numbers separated by commas.")
                    return
            
            # Validate indices
            invalid_indices = [idx for idx in keep_indices if idx < 1 or idx > len(notebooks)]
            if invalid_indices:
                print(f"\n[ERROR] Invalid indices provided: {invalid_indices}. Must be between 1 and {len(notebooks)}.")
                return

            # Separate into keep and delete lists
            to_keep = []
            to_delete = []
            
            for idx, nb in enumerate(notebooks, 1):
                if idx in keep_indices:
                    to_keep.append(nb)
                else:
                    to_delete.append(nb)
                    
            print("\n" + "=" * 60)
            print(" SUMMARY")
            print("=" * 60)
            print(f"Notebooks to KEEP   : {len(to_keep)}")
            print(f"Notebooks to DELETE : {len(to_delete)}")
            
            if not to_delete:
                print("\nNothing to delete. Exiting.")
                return
                
            print("\nThe following notebooks will be DELETED permanently:")
            for nb in to_delete:
                print(f" - {nb.title}")
                
            print("\n" + "!" * 60)
            print(" WARNING: Deletion is permanent and cannot be undone.")
            print("!" * 60)
            
            # 3. Final Confirmation
            confirm = input(f"\nType 'yes' to proceed with deleting {len(to_delete)} notebooks: ").strip().lower()
            
            if confirm != 'yes':
                print("\nOperation cancelled. No notebooks were deleted.")
                return
                
            # 4. Proceed with deletion
            print(f"\nDeleting {len(to_delete)} notebooks...")
            success_count = 0
            
            for i, nb in enumerate(to_delete, 1):
                sys.stdout.write(f"\rDeleting [{i}/{len(to_delete)}] ... ")
                sys.stdout.flush()
                try:
                    await client.notebooks.delete(nb.id)
                    success_count += 1
                except Exception as e:
                    print(f"\n[ERROR] Failed to delete '{nb.title}': {e}")
            
            print(f"\n\nCleanup complete! Successfully deleted {success_count}/{len(to_delete)} notebooks.")

    except Exception as e:
        print(f"\n[FATAL ERROR] {e}")

if __name__ == "__main__":
    # Ensure Windows works correctly with asyncio
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nOperation aborted by user.")
