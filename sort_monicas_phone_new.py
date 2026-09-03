"""
Sort the confirmed-new files from "Monicas Phone" into their correct
year folders (e.g. "2018 Pics and Videos"), based on each file's real
embedded capture date.

Run with --dry-run (default) to review before moving anything.
"""

import argparse
import re
import subprocess
from pathlib import Path

PHOTOS_IMPORT = Path("/mnt/storage_sata/photos-import")


def get_date(f: Path):
    result = subprocess.run(
        ["exiftool", "-s3", "-DateTimeOriginal", "-CreateDate", str(f)],
        capture_output=True, text=True, timeout=15
    )
    lines = [l.strip() for l in result.stdout.strip().split("\n") if l.strip()]
    for line in lines:
        match = re.match(r"^(\d{4}):", line)
        if match:
            return match.group(1)
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    with open("/mnt/storage_sata/monica_phone_new_files.txt") as f:
        files = [Path(line.strip()) for line in f if line.strip()]

    print(f"Files to sort: {len(files)}")

    plan = []
    no_date = []
    for i, f in enumerate(files, 1):
        if not f.exists():
            continue
        year = get_date(f)
        if year is None:
            no_date.append(f)
            continue
        dest_folder = PHOTOS_IMPORT / f"{year} Pics and Videos"
        plan.append((f, dest_folder))
        if i % 500 == 0:
            print(f"  ...processed {i}/{len(files)}")

    print(f"\nFiles with a detected year: {len(plan)}")
    print(f"Files with no date found: {len(no_date)}")

    if no_date:
        print("\nFiles needing manual attention (no date at all - likely a screenshot/download):")
        for f in no_date[:20]:
            print(f"  {f}")
        if len(no_date) > 20:
            print(f"  ... and {len(no_date) - 20} more")

    if not args.apply:
        print("\n--- DRY RUN: first 10 examples ---")
        for f, dest in plan[:10]:
            print(f"  {f.name} -> {dest}")
        print(f"\nRun again with --apply to move these {len(plan)} files.")
        return

    moved = 0
    errors = 0
    for f, dest_folder in plan:
        dest_folder.mkdir(parents=True, exist_ok=True)
        dest_path = dest_folder / f.name
        if dest_path.exists():
            # avoid collision - append a suffix
            dest_path = dest_folder / f"{f.stem}_monica{f.suffix}"
        try:
            f.rename(dest_path)
            moved += 1
        except Exception as e:
            print(f"  ERROR moving {f}: {e}")
            errors += 1

    print(f"\nMoved: {moved}")
    print(f"Errors: {errors}")


if __name__ == "__main__":
    main()
