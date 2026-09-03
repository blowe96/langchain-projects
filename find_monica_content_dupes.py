"""
Find true content duplicates specifically among Immich's flagged
duplicate groups, where files have DIFFERENT filenames but are
genuinely the same content (e.g. "monica 3069.JPG" vs a matching
iOS-timestamped export of the same photo).

Run with --dry-run (default) to review before deleting anything.
"""

import argparse
import hashlib
import subprocess
from collections import defaultdict
from pathlib import Path

PHOTOS_IMPORT_CONTAINER = "/usr/src/app/external/photos-import"
PHOTOS_IMPORT_HOST = Path("/mnt/storage_sata/photos-import")


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

    for dup_id, members in groups.items():
        # Skip groups already handled by the same-filename script
        filenames = set(Path(p).name for _, p in members)
        if len(filenames) == 1:
            continue  # same filename, handled elsewhere

        # Skip the known intentional "Highlights" pattern
        if any("highlights" in p.lower() for _, p in members):
            continue

        checked += 1
        hashes = {}
        for asset_id, path in members:
            host_path = container_path_to_host(path)
            if not host_path.exists():
                continue
            hashes.setdefault(sha256_of(host_path), []).append((asset_id, path))

        for content_hash, matching_files in hashes.items():
            if len(matching_files) > 1:
                # Prefer keeping the "monica" or descriptively-named file over
                # a generic iOS-timestamp export, or just keep the first
                # non-monica one as canonical
                sorted_files = sorted(matching_files, key=lambda x: "monica" in x[1].lower())
                keeper = sorted_files[0]
                for dupe in sorted_files[1:]:
                    confirmed.append((container_path_to_host(dupe[1]), container_path_to_host(keeper[1])))

    print(f"Groups checked (different filenames): {checked}")
    print(f"Confirmed true duplicates (matching SHA-256): {len(confirmed)}")

    if not args.apply:
        print("\n--- DRY RUN: first 20 examples ---")
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
