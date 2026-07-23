"""
Cleanup for true duplicates created by the merge automation copying files
before duplicate detection caught up.
"""

import argparse
import hashlib
import subprocess
from pathlib import Path

PHOTOS_IMPORT_CONTAINER = "/usr/src/app/external/photos-import"
PHOTOS_IMPORT_HOST = Path("/mnt/storage_sata/photos-import")


def run_psql(query: str) -> str:
    result = subprocess.run(
        ["docker", "exec", "immich_postgres", "psql", "-U", "postgres", "-d", "immich",
         "-t", "-A", "-F", "\t", "-c", query],
        capture_output=True, text=True
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

    from collections import defaultdict
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

    candidates = []
    for dup_id, members in groups.items():
        phone_import = [(aid, p) for aid, p in members if "Immich Phone Import" in p]
        others = [(aid, p) for aid, p in members if "Immich Phone Import" not in p]
        if phone_import and others:
            candidates.append((dup_id, phone_import, others))

    print(f"Groups involving an 'Immich Phone Import' copy: {len(candidates)}")

    confirmed_duplicates = []
    for dup_id, phone_import, others in candidates:
        other_asset_id, other_container_path = others[0]
        other_host_path = container_path_to_host(other_container_path)
        if not other_host_path.exists():
            continue
        other_hash = sha256_of(other_host_path)

        for pi_asset_id, pi_container_path in phone_import:
            pi_host_path = container_path_to_host(pi_container_path)
            if not pi_host_path.exists():
                continue
            pi_hash = sha256_of(pi_host_path)
            if pi_hash == other_hash:
                confirmed_duplicates.append((pi_host_path, other_host_path))

    print(f"\nConfirmed true duplicates (matching SHA-256): {len(confirmed_duplicates)}")

    if not args.apply:
        print("\n--- DRY RUN ---")
        print("Sample of files that would be DELETED (the 'Immich Phone Import' copy):")
        for pi_path, keep_path in confirmed_duplicates[:15]:
            print(f"  DELETE: {pi_path}")
            print(f"  KEEP:   {keep_path}")
        print(f"\nRun again with --apply to actually delete these {len(confirmed_duplicates)} files.")
        return

    deleted = 0
    errors = 0
    for pi_path, keep_path in confirmed_duplicates:
        try:
            pi_path.unlink()
            deleted += 1
        except Exception as e:
            print(f"  Error deleting {pi_path}: {e}")
            errors += 1

    print(f"\nDeleted: {deleted}")
    print(f"Errors: {errors}")
    print("\nNext: trigger a rescan of the External Library in Immich to clear these from its database too.")


if __name__ == "__main__":
    main()
