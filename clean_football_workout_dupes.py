"""
Targeted, one-off cleanup for the 'Football Workout' duplicate pattern.
Deliberately narrow - only touches groups where EVERY path contains
"football workout", so it cannot affect the 'Andrew Highlights' pattern.
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

    same_name_candidates = []
    for dup_id, members in groups.items():
        by_filename = defaultdict(list)
        for asset_id, path in members:
            filename = Path(path).name
            by_filename[filename].append((asset_id, path))

        for filename, matches in by_filename.items():
            if len(matches) > 1:
                same_name_candidates.append(matches)

    football_groups = [
        matches for matches in same_name_candidates
        if all("football workout" in p.lower() for _, p in matches)
    ]

    print(f"Football Workout groups found: {len(football_groups)}")

    confirmed = []
    for matches in football_groups:
        if len(matches) != 2:
            print(f"  Skipping unexpected 3+ way group: {matches}")
            continue

        (aid1, p1), (aid2, p2) = matches
        depth1, depth2 = len(Path(p1).parts), len(Path(p2).parts)

        if depth1 != depth2:
            keeper = (aid1, p1) if depth1 < depth2 else (aid2, p2)
            candidate = (aid2, p2) if depth1 < depth2 else (aid1, p1)
        else:
            folder1 = Path(p1).parent.name.lower()
            folder2 = Path(p2).parent.name.lower()
            if "week" in folder1 and "week" not in folder2:
                keeper, candidate = (aid2, p2), (aid1, p1)
            elif "week" in folder2 and "week" not in folder1:
                keeper, candidate = (aid1, p1), (aid2, p2)
            else:
                print(f"  Skipping - can't determine keeper: {p1} vs {p2}")
                continue

        keeper_path = container_path_to_host(keeper[1])
        candidate_path = container_path_to_host(candidate[1])
        if not keeper_path.exists() or not candidate_path.exists():
            continue

        if sha256_of(keeper_path) == sha256_of(candidate_path):
            confirmed.append((candidate_path, keeper_path))

    print(f"\nConfirmed true duplicates (matching SHA-256): {len(confirmed)}")

    if not args.apply:
        print("\n--- DRY RUN ---")
        for delete_path, keep_path in confirmed:
            print(f"  DELETE: {delete_path}")
            print(f"  KEEP:   {keep_path}")
        print(f"\nRun again with --apply to actually delete these {len(confirmed)} files.")
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
