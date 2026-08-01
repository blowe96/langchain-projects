"""
Fix for the 56 highlight/compilation videos with no recoverable date.
Extracts a 4-digit year from the filename or folder name where explicitly
stated, and assigns a reasonable mid-year date (July 1) for that year.

Files with no detectable year are listed separately for manual decision.

Run with --dry-run (default) to review before writing anything.
"""

import argparse
import re
import subprocess
from pathlib import Path

PHOTOS_IMPORT_HOST = Path("/mnt/storage_sata/photos-import")
CONTAINER_PREFIX = "/usr/src/app/external/photos-import/"

with open("/mnt/storage_sata/highlights_56.txt") as f:
    lines = [l.strip() for l in f if l.strip().startswith("/usr/src/app")]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    with_year = []
    no_year = []

    for container_path in lines:
        rel_path = container_path[len(CONTAINER_PREFIX):]
        host_path = PHOTOS_IMPORT_HOST / rel_path

        years_found = re.findall(r"20\d{2}", str(rel_path))
        if years_found:
            year = years_found[-1]
            date = f"{year}:07:01 12:00:00"
            with_year.append((host_path, date, rel_path))
        else:
            no_year.append((host_path, rel_path))

    print(f"Files with a detectable year: {len(with_year)}")
    print(f"Files with NO detectable year (need manual decision): {len(no_year)}")

    if no_year:
        print("\nFiles needing a manual year decision:")
        for host_path, rel_path in no_year:
            print(f"  {rel_path}")

    if not args.apply:
        print("\n--- DRY RUN: first 20 with detected year ---")
        for host_path, date, rel_path in with_year[:20]:
            print(f"  {rel_path} -> {date}")
        print(f"\nRun again with --apply to write these {len(with_year)} date corrections.")
        return

    updated = 0
    errors = 0
    for host_path, date, rel_path in with_year:
        if not host_path.exists():
            print(f"  SKIP (not found): {host_path}")
            errors += 1
            continue
        result = subprocess.run(
            [
                "exiftool", "-overwrite_original",
                f"-QuickTime:CreateDate={date}",
                f"-QuickTime:ModifyDate={date}",
                str(host_path)
            ],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            print(f"  ERROR on {host_path}: {result.stderr.strip()}")
            errors += 1
            continue
        updated += 1

    print(f"\nUpdated: {updated}")
    print(f"Errors: {errors}")


if __name__ == "__main__":
    main()
