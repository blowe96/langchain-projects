"""
DRY RUN: Plan the move of unique (non-duplicate) files remaining in takeout-extracted
into the correct year folder inside photos-import, under a new "Google Photos Import"
subfolder.

This script does NOT move any files. It only prints/reports what WOULD happen,
so the plan can be reviewed before running the real move script.
"""

import json
from pathlib import Path
from datetime import datetime
from collections import defaultdict

TAKEOUT = Path("/mnt/storage_sata/takeout-extracted")
PHOTOS_IMPORT = Path("/mnt/storage_sata/photos-import")

MEDIA_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".mp4", ".mov", ".heic",
    ".gif", ".webp", ".avi", ".mts", ".3gp", ".bmp", ".tiff"
}

PLAN_OUTPUT = Path("/mnt/storage_sata/merge_plan.txt")


def get_year_from_json(media_path: Path):
    json_path = media_path.parent / (media_path.name + ".json")
    if not json_path.exists():
        return None
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        ts = data.get("photoTakenTime", {}).get("timestamp")
        if ts:
            return datetime.fromtimestamp(int(ts)).year
    except (json.JSONDecodeError, KeyError, ValueError, OSError):
        pass
    return None


def get_year_from_filesystem(media_path: Path):
    try:
        return datetime.fromtimestamp(media_path.stat().st_mtime).year
    except OSError:
        return None


def year_to_folder(year: int) -> str:
    if year is None:
        return "Needs Manual Sorting"
    if year <= 2006:
        return "2002 - 2006 Pics and Videos"
    if 2007 <= year <= 2026:
        return f"{year} Pics and Videos"
    return "Needs Manual Sorting"


def main():
    print("Scanning remaining files in takeout-extracted...")

    plan = []
    year_counts = defaultdict(int)
    source_used = defaultdict(int)

    total = 0
    for path in TAKEOUT.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in MEDIA_EXTENSIONS:
            continue
        total += 1
        if total % 5000 == 0:
            print(f"  ...scanned {total} files so far")

        year = get_year_from_json(path)
        source = "json"
        if year is None:
            year = get_year_from_filesystem(path)
            source = "filesystem"
        if year is None:
            source = "none"

        dest_year_folder = year_to_folder(year)
        year_counts[dest_year_folder] += 1
        source_used[source] += 1

        if dest_year_folder == "Needs Manual Sorting":
            dest_path = PHOTOS_IMPORT / "Needs Manual Sorting" / path.name
        else:
            dest_path = PHOTOS_IMPORT / dest_year_folder / "Google Photos Import" / path.name

        plan.append((path, dest_path, source, year))

    print(f"\nTotal files planned: {total}")
    print("\n" + "=" * 60)
    print("BREAKDOWN BY DESTINATION YEAR FOLDER")
    print("=" * 60)
    for folder, count in sorted(year_counts.items()):
        print(f"  {folder:35s} {count:6d} files")

    print("\n" + "=" * 60)
    print("DATE SOURCE USED")
    print("=" * 60)
    for source, count in source_used.items():
        print(f"  {source:15s} {count:6d} files")

    with open(PLAN_OUTPUT, "w") as f:
        f.write(f"MERGE PLAN (DRY RUN) - {total} files\n")
        f.write("=" * 80 + "\n\n")
        for src, dest, source, year in plan:
            f.write(f"[{source}, year={year}]\n")
            f.write(f"  FROM: {src}\n")
            f.write(f"  TO:   {dest}\n\n")

    print(f"\nFull plan written to: {PLAN_OUTPUT}")
    print("Review this file, then run the real move script when ready.")

if __name__ == "__main__":
    main()
