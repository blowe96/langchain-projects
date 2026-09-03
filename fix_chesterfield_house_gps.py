"""
Assign GPS coordinates to the "2004_05_07 Chesterfield House Being Built"
folder, using the confirmed Chesterfield, Michigan home coordinates from
the earlier Tier 2 home-era GPS project.

Run with --dry-run (default) to review before writing anything.
"""

import argparse
import subprocess
from pathlib import Path

FOLDER = Path("/mnt/storage_sata/photos-import/1997 - 2006 Pics and Videos/2004_05_07 Chesterfield House Being Built")
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".avi", ".gif"}

LAT = 42.68643
LON = -82.8392652


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    files = [f for f in FOLDER.iterdir() if f.is_file()]
    print(f"Files to correct: {len(files)}")

    if not args.apply:
        print("\n--- DRY RUN: first 10 examples ---")
        for f in files[:10]:
            print(f"  {f.name} -> lat={LAT}, lon={LON}")
        print(f"\nRun again with --apply to write these {len(files)} GPS updates.")
        return

    updated = 0
    errors = 0
    for f in files:
        is_video = f.suffix.lower() in VIDEO_EXTENSIONS
        if is_video:
            cmd = ["exiftool", "-overwrite_original", f"-XMP:GPSLatitude={LAT}", f"-XMP:GPSLongitude={LON}", str(f)]
        else:
            lat_ref = "N" if LAT >= 0 else "S"
            lon_ref = "E" if LON >= 0 else "W"
            cmd = ["exiftool", "-overwrite_original",
                   f"-GPSLatitude={abs(LAT)}", f"-GPSLatitudeRef={lat_ref}",
                   f"-GPSLongitude={abs(LON)}", f"-GPSLongitudeRef={lon_ref}", str(f)]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            print(f"  ERROR on {f}: {result.stderr.strip()}")
            errors += 1
            continue
        updated += 1

    print(f"\nUpdated: {updated}")
    print(f"Errors: {errors}")


if __name__ == "__main__":
    main()
