"""
Leg 1 of the backup workflow: copy new mobile-uploaded photos/videos from
Immich's managed storage into photos-import.

Now includes a safety check: skips the run entirely if Immich's Duplicate
Detection hasn't caught up on at least 99% of active/visible assets, to
prevent creating duplicate copies inside photos-import during a large sync.
"""

import argparse
import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

PHOTOS_IMPORT = Path("/mnt/storage_sata/photos-import")
IMMICH_UPLOAD_ROOT = Path("/mnt/storage_sata/immich-app/library")
MANIFEST_PATH = Path("/mnt/storage_sata/immich_merge_manifest.json")


def run_psql(query: str) -> str:
    result = subprocess.run(
        ["docker", "exec", "immich_postgres", "psql", "-U", "postgres", "-d", "immich",
         "-t", "-A", "-F", "\t", "-c", query],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"psql error: {result.stderr}")
    return result.stdout


def load_manifest():
    if MANIFEST_PATH.exists():
        with open(MANIFEST_PATH) as f:
            return set(json.load(f))
    return set()


def save_manifest(copied_ids):
    with open(MANIFEST_PATH, "w") as f:
        json.dump(sorted(copied_ids), f)


def year_to_folder(year: int) -> str:
    if year <= 2006:
        return "2002 - 2006 Pics and Videos"
    return f"{year} Pics and Videos"


def unique_destination(dest: Path) -> Path:
    if not dest.exists():
        return dest
    stem = dest.stem
    suffix = dest.suffix
    parent = dest.parent
    counter = 2
    while True:
        candidate = parent / f"{stem}_dup{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def check_duplicate_detection_ready(min_coverage=0.99) -> bool:
    query = """
        SELECT
            COUNT(*) AS total,
            COUNT(ajs."duplicatesDetectedAt") AS done
        FROM asset a
        LEFT JOIN asset_job_status ajs ON a.id = ajs."assetId"
        WHERE a.status = 'active' AND a.visibility = 'timeline';
    """
    raw = run_psql(query)
    line = raw.strip().split("\n")[0]
    total_str, done_str = line.split("\t")
    total, done = int(total_str), int(done_str)
    if total == 0:
        return True
    coverage = done / total
    print(f"Duplicate detection coverage: {done}/{total} ({coverage*100:.1f}%)")
    return coverage >= min_coverage


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true", help="Skip the duplicate-detection readiness check")
    args = parser.parse_args()

    if not args.force:
        print("Checking whether Immich's duplicate detection has caught up...")
        if not check_duplicate_detection_ready():
            print("Duplicate detection coverage is below 99% - skipping this run to avoid")
            print("creating premature duplicates. Try again later, or re-run with --force")
            print("if you're confident this is safe (not recommended during a large sync).")
            return

    print("Querying Immich for mobile-uploaded active assets...")
    query = """
        SELECT id, "originalPath", "localDateTime", "originalFileName"
        FROM asset
        WHERE status = 'active' AND "originalPath" LIKE '/data/%' AND "duplicateId" IS NULL;
    """
    raw = run_psql(query)

    rows = []
    for line in raw.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) != 4:
            continue
        rows.append(parts)

    print(f"Total mobile-uploaded active assets in Immich: {len(rows)}")

    already_copied = load_manifest()
    print(f"Already copied in previous runs: {len(already_copied)}")

    to_copy = [(aid, path, date, fname) for aid, path, date, fname in rows if aid not in already_copied]
    print(f"New files to copy this run: {len(to_copy)}")

    if not to_copy:
        print("Nothing new to copy.")
        return

    plan = []
    for asset_id, container_path, local_date, original_filename in to_copy:
        if not container_path.startswith("/data/"):
            continue
        real_path = IMMICH_UPLOAD_ROOT / container_path[len("/data/"):]
        if not real_path.exists():
            print(f"  WARNING: file not found on disk, skipping: {real_path}")
            continue

        try:
            year = int(local_date[:4])
        except (ValueError, IndexError):
            year = datetime.now().year

        dest_dir = PHOTOS_IMPORT / year_to_folder(year) / "Immich Phone Import"
        dest_path = dest_dir / original_filename
        plan.append((asset_id, real_path, dest_path, dest_dir))

    if args.dry_run:
        print(f"\n--- DRY RUN: {len(plan)} files would be copied ---")
        for asset_id, real_path, dest_path, _ in plan[:20]:
            print(f"  {real_path} -> {dest_path}")
        if len(plan) > 20:
            print(f"  ... and {len(plan) - 20} more")
        return

    copied_count = 0
    errors = 0
    for i, (asset_id, real_path, dest_path, dest_dir) in enumerate(plan, 1):
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
            final_dest = unique_destination(dest_path)
            shutil.copy2(real_path, final_dest)
            already_copied.add(asset_id)
            copied_count += 1
        except Exception as e:
            print(f"  Error copying {real_path}: {e}")
            errors += 1

        if i % 100 == 0:
            save_manifest(already_copied)
            print(f"  ...copied {i}/{len(plan)}")

    save_manifest(already_copied)

    print("\n" + "=" * 60)
    print("MERGE COMPLETE")
    print("=" * 60)
    print(f"Files copied: {copied_count}")
    print(f"Errors: {errors}")
    print("\nNext steps:")
    print("1. Trigger a rescan of the External Library in Immich (or wait for the daily scan)")
    print("2. Once Duplicate Detection catches up, run resolve_duplicates.py to clean up")


if __name__ == "__main__":
    main()
