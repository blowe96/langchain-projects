"""
Clean up mobile-upload assets that already have a matching file (by
filename AND SHA-256 hash) safely archived in photos-import, but weren't
caught by Immich's own Duplicate Detection (likely due to Immich's
perceptual/visual hash being less reliable for video content than a
true byte-level comparison).

Run with --dry-run (default) to review before trashing anything.
"""

import argparse
import hashlib
import subprocess
from pathlib import Path

PHOTOS_IMPORT = Path("/mnt/storage_sata/photos-import")
IMMICH_LIBRARY = Path("/mnt/storage_sata/immich-app/library")


def run_psql(query: str) -> str:
    result = subprocess.run(
        ["docker", "exec", "-i", "immich_postgres", "psql", "-U", "postgres", "-d", "immich",
         "-t", "-A", "-F", "\t"],
        input=query, capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"psql error: {result.stderr}")
    return result.stdout


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

    print("Fetching mobile-upload assets...")
    query = """
        SELECT id, "originalFileName", "originalPath"
        FROM asset
        WHERE "originalPath" LIKE '/data/%' AND status = 'active';
    """
    raw = run_psql(query)

    rows = []
    for line in raw.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        rows.append(tuple(parts))

    print(f"Total mobile-upload assets: {len(rows)}")

    confirmed = []
    no_match = []

    for i, (asset_id, filename, container_path) in enumerate(rows, 1):
        matches = list(PHOTOS_IMPORT.rglob(filename))
        if not matches:
            no_match.append((asset_id, filename))
            continue

        # Find the actual mobile file on disk to hash-compare
        rel = container_path[len("/data/"):]
        mobile_host_path = IMMICH_LIBRARY / rel
        if not mobile_host_path.exists():
            no_match.append((asset_id, filename))
            continue

        mobile_hash = sha256_of(mobile_host_path)
        found_match = False
        for m in matches:
            if sha256_of(m) == mobile_hash:
                confirmed.append((asset_id, filename, m))
                found_match = True
                break
        if not found_match:
            no_match.append((asset_id, filename))

        if i % 500 == 0:
            print(f"  ...checked {i}/{len(rows)}")

    print(f"\nConfirmed true duplicates (hash-verified): {len(confirmed)}")
    print(f"No confirmed match (leave alone): {len(no_match)}")

    if not args.apply:
        print("\n--- DRY RUN: first 15 examples ---")
        for asset_id, filename, archive_path in confirmed[:15]:
            print(f"  {filename} -> matches {archive_path}")
        print(f"\nRun again with --apply to trash these {len(confirmed)} mobile-upload duplicates.")
        return

    trashed = 0
    errors = 0
    for asset_id, filename, archive_path in confirmed:
        result = subprocess.run(
            ["docker", "exec", "-i", "immich_postgres", "psql", "-U", "postgres", "-d", "immich", "-c",
             f"UPDATE asset SET status = 'trashed', \"deletedAt\" = now() WHERE id = '{asset_id}';"],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            errors += 1
            continue
        trashed += 1

    print(f"\nTrashed: {trashed}")
    print(f"Errors: {errors}")


if __name__ == "__main__":
    main()
