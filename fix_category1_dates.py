"""
Fix for photos with zero embedded date, sitting in a folder whose name
gives us a real date (either an exact date like '2019_12_28 Chicago Trip'
or just a year like '2012_New House in Chesterfield').

Run with --dry-run (default) to review before writing anything.
"""

import argparse
import subprocess
from pathlib import Path

PHOTOS_IMPORT_HOST = Path("/mnt/storage_sata/photos-import")

# (relative path, date to assign - noon on that day/year as a reasonable default)
FILES = [
    ("2012 Pics and Videos/2012_New House in Chesterfield/29.jpg", "2012:06:24 12:00:00"),
    ("2012 Pics and Videos/2012_New House in Chesterfield/31.jpg", "2012:06:24 12:00:00"),
    ("2012 Pics and Videos/2012_New House in Chesterfield/3.jpg", "2012:06:24 12:00:00"),
    ("2012 Pics and Videos/2012_New House in Chesterfield/64.jpg", "2012:06:24 12:00:00"),
    ("2012 Pics and Videos/2012_New House in Chesterfield/65.jpg", "2012:06:24 12:00:00"),
    ("2012 Pics and Videos/2012_New House in Chesterfield/67.jpg", "2012:06:24 12:00:00"),
    ("2012 Pics and Videos/2012_New House in Chesterfield/68.jpg", "2012:06:24 12:00:00"),
    ("2012 Pics and Videos/2012_New House in Chesterfield/74.jpg", "2012:06:24 12:00:00"),
    ("2012 Pics and Videos/2012_New House in Chesterfield/DSC08936.jpg", "2012:06:24 12:00:00"),
    ("2019 Pics and Videos/2019_12_28 Chicago Trip/2019_12_28 (3).jpg", "2019:12:28 12:00:00"),
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    print(f"Files to correct: {len(FILES)}")

    if not args.apply:
        print("\n--- DRY RUN ---")
        for rel_path, date in FILES:
            host_path = PHOTOS_IMPORT_HOST / rel_path
            exists = "EXISTS" if host_path.exists() else "MISSING"
            print(f"  [{exists}] {rel_path} -> {date}")
        print("\nRun again with --apply to write these corrections.")
        return

    updated = 0
    errors = 0
    for rel_path, date in FILES:
        host_path = PHOTOS_IMPORT_HOST / rel_path
        if not host_path.exists():
            print(f"  SKIP (not found): {host_path}")
            errors += 1
            continue

        result = subprocess.run(
            [
                "exiftool", "-overwrite_original",
                f"-DateTimeOriginal={date}",
                f"-CreateDate={date}",
                str(host_path)
            ],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            print(f"  ERROR on {host_path}: {result.stderr.strip()}")
            errors += 1
            continue
        print(f"  Updated: {host_path}")
        updated += 1

    print(f"\nUpdated: {updated}")
    print(f"Errors: {errors}")


if __name__ == "__main__":
    main()
