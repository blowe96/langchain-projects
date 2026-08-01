"""
Find and clean up files renamed with a trailing "11" during manual folder
reorganization (added to resolve filename collisions when moving files
into a shared year folder). For each candidate, strip the trailing "11",
search the archive for a file matching that original name, and verify
via SHA-256 that it's genuinely the same content before proposing deletion.

Run with --dry-run (default) to review before deleting anything.
"""

import argparse
import hashlib
import re
import subprocess
from pathlib import Path

PHOTOS_IMPORT_HOST = Path("/mnt/storage_sata/photos-import")


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    with open("/mnt/storage_sata/renamed_11_candidates.txt") as f:
        candidates = [Path(line.strip()) for line in f if line.strip()]

    print(f"Total candidates: {len(candidates)}")

    print("Building filename index of entire archive...")
    all_files = list(PHOTOS_IMPORT_HOST.rglob("*"))
    by_name = {}
    for f in all_files:
        if f.is_file():
            by_name.setdefault(f.name, []).append(f)

    confirmed = []
    no_match = []

    for c in candidates:
        stem = c.stem
        suffix = c.suffix
        if not stem.endswith("11"):
            no_match.append((c, "doesn't end in 11"))
            continue
        original_name = stem[:-2] + suffix

        if original_name not in by_name:
            no_match.append((c, f"no file named {original_name} found"))
            continue

        matches = [f for f in by_name[original_name] if f != c]
        if not matches:
            no_match.append((c, "no distinct match found"))
            continue

        c_hash = sha256_of(c)
        found_match = False
        for m in matches:
            if sha256_of(m) == c_hash:
                confirmed.append((c, m))
                found_match = True
                break
        if not found_match:
            no_match.append((c, f"found {original_name} but content differs"))

    print(f"\nConfirmed true duplicates (safe to delete): {len(confirmed)}")
    print(f"No confirmed match (leave alone): {len(no_match)}")

    if no_match:
        print("\nFiles left alone:")
        for c, reason in no_match:
            print(f"  {c} - {reason}")

    if not args.apply:
        print("\n--- DRY RUN ---")
        for delete_path, keep_path in confirmed[:20]:
            print(f"  DELETE: {delete_path}")
            print(f"  KEEP:   {keep_path}")
        if len(confirmed) > 20:
            print(f"  ... and {len(confirmed) - 20} more")
        print(f"\nRun again with --apply to delete these {len(confirmed)} files.")
        return

    deleted = 0
    errors = 0
    for delete_path, keep_path in confirmed:
        try:
            delete_path.unlink()
            deleted += 1
        except Exception as e:
            print(f"  Error deleting {delete_path}: {e}")
            errors += 1

    print(f"\nDeleted: {deleted}")
    print(f"Errors: {errors}")


if __name__ == "__main__":
    main()
