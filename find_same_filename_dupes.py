"""
Find true duplicates where the exact same filename exists in two different
locations within photos-import. Prefers keeping the copy in a descriptively
named folder over a generic Share/SHARE folder or bare year folder.

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


def is_generic_folder(path_str: str) -> bool:
    """A folder is 'generic' if its name ends in 'share' (e.g. 'Share',
    'Jordan SHARE', 'James SHARE'), or if it's just a bare
    'YYYY Pics and Videos' folder with nothing else."""
    parent_name = Path(path_str).parent.name.lower()
    if parent_name.endswith("share") or parent_name.endswith("sharing"):
        return True
    if parent_name.endswith("pics and videos"):
        return True
    return False


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

    same_name_candidates = []
    for dup_id, members in groups.items():
        by_filename = defaultdict(list)
        for asset_id, path in members:
            filename = Path(path).name
            by_filename[filename].append((asset_id, path))

        for filename, matches in by_filename.items():
            if len(matches) > 1:
                same_name_candidates.append(matches)

    print(f"Groups with matching filenames in multiple locations: {len(same_name_candidates)}")

    confirmed = []
    skipped_ambiguous = []
    for matches in same_name_candidates:
        non_generic = [(aid, p) for aid, p in matches if not is_generic_folder(p)]
        generic = [(aid, p) for aid, p in matches if is_generic_folder(p)]

        if len(non_generic) == 1 and generic:
            keeper_id, keeper_path_str = non_generic[0]
            candidates = generic
        elif len(non_generic) == 0 and len(matches) == 2:
            matches_with_depth = [(len(Path(p).parts), aid, p) for aid, p in matches]
            matches_with_depth.sort(reverse=True)
            keeper_id, keeper_path_str = matches_with_depth[0][1], matches_with_depth[0][2]
            candidates = [(aid, p) for _, aid, p in matches_with_depth[1:]]
        else:
            skipped_ambiguous.append(matches)
            continue

        keeper_path = container_path_to_host(keeper_path_str)
        if not keeper_path.exists():
            continue
        keeper_hash = sha256_of(keeper_path)

        for asset_id, path in candidates:
            candidate_path = container_path_to_host(path)
            if not candidate_path.exists():
                continue
            if sha256_of(candidate_path) == keeper_hash:
                confirmed.append((candidate_path, keeper_path))

    print(f"\nConfirmed true duplicates (matching SHA-256): {len(confirmed)}")
    print(f"Skipped as ambiguous (needs manual judgment): {len(skipped_ambiguous)}")

    if skipped_ambiguous:
        with open("/mnt/storage_sata/ambiguous_same_filename.txt", "w") as f:
            f.write(f"AMBIGUOUS SAME-FILENAME GROUPS - {len(skipped_ambiguous)} groups\n")
            f.write("=" * 80 + "\n\n")
            for matches in skipped_ambiguous:
                f.write(f"Filename: {Path(matches[0][1]).name}\n")
                for asset_id, path in matches:
                    f.write(f"    {path}\n")
                f.write("\n")
        print(f"Ambiguous groups written to: /mnt/storage_sata/ambiguous_same_filename.txt")

    if not args.apply:
        print("\n--- DRY RUN ---")
        for delete_path, keep_path in confirmed[:20]:
            print(f"  DELETE: {delete_path}")
            print(f"  KEEP:   {keep_path}")
        if len(confirmed) > 20:
            print(f"  ... and {len(confirmed) - 20} more")
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
    print("\nNext: trigger a rescan of the External Library in Immich.")


if __name__ == "__main__":
    main()
