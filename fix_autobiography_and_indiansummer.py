"""
Two fixes:
1. IMG_43861.jpg in "2018_Brianne's Autobiography" - single outlier
   dragging the whole album's date grouping into the wrong year.
2. All 103 files in "2011_06_01 Pictures of house on Indian Summer Dr" -
   carry a 2023 batch-scan date instead of the real 2011 date stated in
   the folder name.

Run with --dry-run (default) to review before writing anything.
"""

import argparse
import subprocess
from pathlib import Path

PHOTOS_IMPORT_HOST = Path("/mnt/storage_sata/photos-import")

AUTOBIOGRAPHY_FIX = (
    "2018 Pics and Videos/2018_Brianne's Autobiography/IMG_43861.jpg",
    "2018:12:15 12:00:00"
)

INDIAN_SUMMER_DATE = "2011:06:01 12:00:00"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    with open("/mnt/storage_sata/indian_summer_103.txt", encoding="utf-8") as f:
        indian_summer_paths = [
            line.strip() for line in f
            if line.strip().startswith("/usr/src/app")
        ]

    print(f"Autobiography fix: 1 file")
    print(f"Indian Summer Dr fix: {len(indian_summer_paths)} files")

    all_files = [(AUTOBIOGRAPHY_FIX[0], AUTOBIOGRAPHY_FIX[1])]
    for p in indian_summer_paths:
        rel = p[len("/usr/src/app/external/photos-import/"):]
        all_files.append((rel, INDIAN_SUMMER_DATE))

    if not args.apply:
        print("\n--- DRY RUN: first 10 examples ---")
        for rel_path, date in all_files[:10]:
            host_path = PHOTOS_IMPORT_HOST / rel_path
            exists = "EXISTS" if host_path.exists() else "MISSING"
            print(f"  [{exists}] {rel_path} -> {date}")
        print(f"\nRun again with --apply to write these {len(all_files)} corrections.")
        return

    updated = 0
    errors = 0
    for rel_path, date in all_files:
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
        updated += 1

    print(f"\nUpdated: {updated}")
    print(f"Errors: {errors}")


if __name__ == "__main__":
    main()
