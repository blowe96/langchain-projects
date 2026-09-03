"""
Find true duplicates among Immich's flagged duplicate groups by comparing
CONTENT ONLY - stripping all metadata (via exiftool -all=) before hashing,
so files that are visually/audibly identical but have different EXIF
(e.g. because our own GPS/date-writing scripts touched one copy and not
the other) are still correctly recognized as duplicates.

Run with --dry-run (default) to review before deleting anything.
"""

import argparse
import hashlib
import shutil
import subprocess
import tempfile
from collections import defaultdict
from pathlib import Path

PHOTOS_IMPORT_CONTAINER = "/usr/src/app/external/photos-import"
PHOTOS_IMPORT_HOST = Path("/mnt/storage_sata/photos-import")

# Folders/patterns to never touch (intentional duplicates)
SKIP_PATTERNS = ["highlights", "andrew lowe"]


def run_psql(query: str) -> str:
    result = subprocess.run(
        ["docker", "exec", "-i", "immich_postgres", "psql", "-U", "postgres", "-d", "immich",
         "-t", "-A", "-F", "\t"],
        input=query, capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"psql error: {result.stderr}")
    return result.stdout


def container_path_to_host(container_path: str) -> Path:
    rel = container_path[len(PHOTOS_IMPORT_CONTAINER):].lstrip("/")
    return PHOTOS_IMPORT_HOST / rel


def stripped_hash(path: Path, tmpdir: Path) -> str:
    """Copy file, strip all metadata, hash the result - compares true
    underlying content only, immune to any metadata differences."""
    tmp_copy = tmpdir / f"strip_{path.name}"
    shutil.copy2(path, tmp_copy)
    subprocess.run(
        ["exiftool", "-all=", "-overwrite_original", str(tmp_copy)],
        capture_output=True, text=True, timeout=30
    )
    h = hashlib.sha256()
    with open(tmp_copy, "rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    tmp_copy.unlink()
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    print("Fetching duplicate groups from Immich...")
    query = """
        SELECT "duplicateId", id, "originalPath"
        FROM asset
        WHERE status = 'active' AND "duplicateId" IS NOT NULL;
    """
    raw = run_psql(query)

    groups = defaultdict(list)
    for line in raw.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        dup_id, asset_id, path = parts
        groups[dup_id].append((asset_id, path))

    print(f"Total duplicate groups: {len(groups)}")

    confirmed = []
    checked = 0
    skipped_intentional = 0

    with tempfile.TemporaryDirectory() as tmpdir_str:
        tmpdir = Path(tmpdir_str)

        for dup_id, members in groups.items():
            if any(any(pat in p.lower() for pat in SKIP_PATTERNS) for _, p in members):
                skipped_intentional += 1
                continue

            checked += 1
            if checked % 200 == 0:
                print(f"  ...checked {checked}/{len(groups)} groups")

            hashes = {}
            for asset_id, path in members:
                host_path = container_path_to_host(path)
                if not host_path.exists():
                    continue
                try:
                    h = stripped_hash(host_path, tmpdir)
                except Exception:
                    continue
                hashes.setdefault(h, []).append((asset_id, path))

            for content_hash, matching_files in hashes.items():
                if len(matching_files) > 1:
                    # Prefer to KEEP: a file in a named event subfolder over
                    # a flat year-folder file; otherwise keep the first
                    def depth_score(item):
                        return len(Path(item[1]).parts)
                    sorted_files = sorted(matching_files, key=depth_score, reverse=True)
                    keeper = sorted_files[0]
                    for dupe in sorted_files[1:]:
                        confirmed.append((container_path_to_host(dupe[1]), container_path_to_host(keeper[1])))

    print(f"\nGroups checked: {checked}")
    print(f"Groups skipped (intentional Highlights pattern): {skipped_intentional}")
    print(f"Confirmed true duplicates (content-only match): {len(confirmed)}")

    if not args.apply:
        with open("/mnt/storage_sata/content_dupes_full_pairs.txt", "w") as f:
            for delete_path, keep_path in confirmed:
                f.write(f"DELETE: {delete_path}\n")
                f.write(f"KEEP:   {keep_path}\n")
        print(f"\nFull pair list written to: /mnt/storage_sata/content_dupes_full_pairs.txt")
        print("\n--- DRY RUN: first 25 examples ---")
        for delete_path, keep_path in confirmed[:25]:
            print(f"  DELETE: {delete_path}")
            print(f"  KEEP:   {keep_path}")
        if len(confirmed) > 25:
            print(f"  ... and {len(confirmed) - 25} more")
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
