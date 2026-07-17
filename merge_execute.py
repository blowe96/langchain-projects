"""
EXECUTE: Move unique (non-duplicate) files from takeout-extracted into the correct
year folder inside photos-import, under a "Google Photos Import" subfolder.

Safety features:
  - Collision-safe: if a destination filename already exists, a numeric suffix
    is appended rather than overwriting anything.
  - A manifest (tab-separated) is written recording every original path and
    its final destination path, for full traceability.
"""

import json
import shutil
from pathlib import Path
from datetime import datetime
from collections import defaultdict

TAKEOUT = Path("/mnt/storage_sata/takeout-extracted")
PHOTOS_IMPORT = Path("/mnt/storage_sata/photos-import")

MEDIA_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".mp4", ".mov", ".heic",
    ".gif", ".webp", ".avi", ".mts", ".3gp", ".bmp", ".tiff"
}

MANIFEST_PATH = Path("/mnt/storage_sata/merge_manifest.txt")


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


def year_to_folder(year):
    if year is None:
        return "Needs Manual Sorting"
    if year <= 2006:
        return "2002 - 2006 Pics and Videos"
    if 2007 <= year <= 2026:
        return f"{year} Pics and Videos"
    return "Needs Manual Sorting"


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


def main():
    print("Scanning and moving unique files from takeout-extracted...")

    year_counts = defaultdict(int)
    source_used = defaultdict(int)
    collisions_renamed = 0
    moved = 0
    errors = 0

    all_files = [
        p for p in TAKEOUT.rglob("*")
        if p.is_file() and p.suffix.lower() in MEDIA_EXTENSIONS
    ]
    total = len(all_files)
    print(f"Total files to process: {total}")

    with open(MANIFEST_PATH, "w") as manifest:
        manifest.write("original_path\tfinal_path\tdate_source\tyear\n")

        for path in all_files:
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
                dest_dir = PHOTOS_IMPORT / "Needs Manual Sorting"
            else:
                dest_dir = PHOTOS_IMPORT / dest_year_folder / "Google Photos Import"

            dest_dir.mkdir(parents=True, exist_ok=True)
            dest_path = dest_dir / path.name

            final_dest = unique_destination(dest_path)
            if final_dest != dest_path:
                collisions_renamed += 1

            try:
                shutil.move(str(path), str(final_dest))
                manifest.write(f"{path}\t{final_dest}\t{source}\t{year}\n")
                moved += 1
                if moved % 2000 == 0:
                    print(f"  ...moved {moved}/{total} files")
            except (OSError, shutil.Error) as e:
                print(f"  ERROR moving {path}: {e}")
                errors += 1

    print("\n" + "=" * 60)
    print("MERGE COMPLETE")
    print("=" * 60)
    print(f"Files moved successfully:     {moved}")
    print(f"Filename collisions renamed:  {collisions_renamed}")
    print(f"Errors:                       {errors}")
    print(f"\nBreakdown by destination year folder:")
    for folder, count in sorted(year_counts.items()):
        print(f"  {folder:35s} {count:6d} files")
    print(f"\nManifest written to: {MANIFEST_PATH}")

if __name__ == "__main__":
    main()
