"""
Assign real dates to the "New Pics" batch (old scanned photos from
OneDrive, 1997-2003) using their date-named subfolders as the source
of truth.

Run with --dry-run (default) to review before writing anything.
"""

import argparse
import re
import subprocess
from pathlib import Path

BASE = Path("/mnt/storage_sata/New Pics")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    plan = []
    for subdir in sorted(BASE.iterdir()):
        if not subdir.is_dir():
            continue
        match = re.match(r"^(\d{4})_(\d{2})_(\d{2})$", subdir.name)
        if not match:
            print(f"  SKIP (folder name doesn't match date pattern): {subdir}")
            continue
        year, month, day = match.groups()
        date = f"{year}:{month}:{day} 12:00:00"
        for f in subdir.iterdir():
            if f.is_file():
                plan.append((f, date))

    print(f"Files to correct: {len(plan)}")

    if not args.apply:
        print("\n--- DRY RUN ---")
        for f, date in plan:
            print(f"  {f} -> {date}")
        print(f"\nRun again with --apply to write these {len(plan)} date corrections.")
        return

    updated = 0
    errors = 0
    for f, date in plan:
        result = subprocess.run(
            [
                "exiftool", "-overwrite_original",
                f"-DateTimeOriginal={date}",
                f"-CreateDate={date}",
                str(f)
            ],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            print(f"  ERROR on {f}: {result.stderr.strip()}")
            errors += 1
            continue
        updated += 1

    print(f"\nUpdated: {updated}")
    print(f"Errors: {errors}")


if __name__ == "__main__":
    main()
