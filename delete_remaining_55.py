"""
Delete the 55 remaining photos with no recoverable date - user has
manually verified each one is either a genuine duplicate (found the
correctly-dated copy elsewhere in the archive) or not needed.

Run with --dry-run (default) to review before deleting anything.
"""

import argparse
from pathlib import Path

PHOTOS_IMPORT_HOST = Path("/mnt/storage_sata/photos-import")
CONTAINER_PREFIX = "/usr/src/app/external/photos-import/"

with open("/mnt/storage_sata/remaining_65.txt", encoding="utf-8") as f:
    paths = [
        line.strip()[len(CONTAINER_PREFIX):]
        for line in f
        if line.strip().startswith("/usr/src/app")
    ]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    print(f"Files to delete: {len(paths)}")

    if not args.apply:
        print("\n--- DRY RUN ---")
        for rel_path in paths:
            host_path = PHOTOS_IMPORT_HOST / rel_path
            exists = "EXISTS" if host_path.exists() else "MISSING"
            print(f"  [{exists}] {rel_path}")
        print(f"\nRun again with --apply to delete these {len(paths)} files.")
        return

    deleted = 0
    errors = 0
    for rel_path in paths:
        host_path = PHOTOS_IMPORT_HOST / rel_path
        if not host_path.exists():
            print(f"  SKIP (not found): {host_path}")
            errors += 1
            continue
        try:
            host_path.unlink()
            deleted += 1
        except Exception as e:
            print(f"  Error deleting {host_path}: {e}")
            errors += 1

    print(f"\nDeleted: {deleted}")
    print(f"Errors: {errors}")


if __name__ == "__main__":
    main()
