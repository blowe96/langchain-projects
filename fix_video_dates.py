"""
Recovery for video files whose primary QuickTime date fields got blanked
out, using the surviving Track Modify Date as the source of truth.
"""

import argparse
import subprocess
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


def get_track_modify_date(host_path: Path):
    result = subprocess.run(
        ["exiftool", "-s3", "-Track1:TrackModifyDate", str(host_path)],
        capture_output=True, text=True, timeout=15
    )
    date_str = result.stdout.strip()
    if not date_str or date_str.startswith("0000"):
        return None
    return date_str


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    print("Fetching affected video assets (showing this week's dates)...")
    query = """
        SELECT "originalPath"
        FROM asset a
        WHERE a.status = 'active'
        AND (a."originalPath" ILIKE '%.mp4' OR a."originalPath" ILIKE '%.mov')
        AND a."localDateTime" >= '2026-07-24' AND a."localDateTime" < '2026-08-01';
    """
    raw = run_psql(query)
    paths = [line.strip() for line in raw.strip().split("\n") if line.strip()]
    print(f"Total affected videos: {len(paths)}")

    plan = []
    no_recovery = []
    for container_path in paths:
        host_path = container_path_to_host(container_path)
        if not host_path.exists():
            no_recovery.append((container_path, "file not found"))
            continue
        recovered_date = get_track_modify_date(host_path)
        if recovered_date is None:
            no_recovery.append((container_path, "Track Modify Date also blank"))
            continue
        plan.append((host_path, recovered_date))

    print(f"\nFiles with a recoverable date: {len(plan)}")
    print(f"Files WITHOUT a recoverable date: {len(no_recovery)}")

    if no_recovery:
        print("\nFiles needing manual attention:")
        for path, reason in no_recovery[:20]:
            print(f"  {path} - {reason}")
        if len(no_recovery) > 20:
            print(f"  ... and {len(no_recovery) - 20} more")

    if not args.apply:
        print("\n--- DRY RUN: first 15 examples ---")
        for host_path, recovered_date in plan[:15]:
            print(f"  {host_path}")
            print(f"    -> restore date: {recovered_date}")
        print(f"\nRun again with --apply to write these {len(plan)} date corrections.")
        return

    updated = 0
    errors = 0
    for i, (host_path, recovered_date) in enumerate(plan, 1):
        result = subprocess.run(
            [
                "exiftool", "-overwrite_original",
                f"-QuickTime:CreateDate={recovered_date}",
                f"-QuickTime:ModifyDate={recovered_date}",
                str(host_path)
            ],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            print(f"  ERROR on {host_path}: {result.stderr.strip()}")
            errors += 1
            continue
        updated += 1
        if i % 200 == 0:
            print(f"  ...processed {i}/{len(plan)} (updated: {updated}, errors: {errors})")

    print(f"\nUpdated: {updated}")
    print(f"Errors: {errors}")
    print("\nNext: trigger a rescan of the External Library in Immich.")


if __name__ == "__main__":
    main()
