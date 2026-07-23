"""
Remove leftover Picasa software artifacts from photos-import.
"""

import argparse
import shutil
from pathlib import Path

PHOTOS_ROOT = Path("/mnt/storage_sata/photos-import")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    ini_files = list(PHOTOS_ROOT.rglob(".picasa.ini"))
    originals_dirs = list(PHOTOS_ROOT.rglob(".picasaoriginals"))
    originals_dirs = [d for d in originals_dirs if d.is_dir()]

    total_ini_size = sum(f.stat().st_size for f in ini_files)
    total_originals_size = sum(
        f.stat().st_size for d in originals_dirs for f in d.rglob("*") if f.is_file()
    )

    print(f".picasa.ini files found: {len(ini_files)} ({total_ini_size / 1024:.1f} KB)")
    print(f".picasaoriginals folders found: {len(originals_dirs)} ({total_originals_size / (1024*1024):.1f} MB)")

    if not args.apply:
        print("\n--- DRY RUN ---")
        print("Sample .picasa.ini files:")
        for f in ini_files[:5]:
            print(f"  {f}")
        print("Sample .picasaoriginals folders:")
        for d in originals_dirs[:5]:
            print(f"  {d}")
        print("\nRun again with --apply to actually delete these.")
        return

    deleted_files = 0
    deleted_dirs = 0
    errors = 0

    for f in ini_files:
        try:
            f.unlink()
            deleted_files += 1
        except Exception as e:
            print(f"  Error deleting {f}: {e}")
            errors += 1

    for d in originals_dirs:
        try:
            shutil.rmtree(d)
            deleted_dirs += 1
        except Exception as e:
            print(f"  Error deleting {d}: {e}")
            errors += 1

    print(f"\nDeleted {deleted_files} .picasa.ini files")
    print(f"Deleted {deleted_dirs} .picasaoriginals folders")
    print(f"Errors: {errors}")


if __name__ == "__main__":
    main()
