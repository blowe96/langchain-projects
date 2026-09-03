"""
Assign date (May 7, 2004) and GPS (Chesterfield, Michigan) to the
complete "Chesterfield House" photo set - a fuller re-download from
OneDrive replacing yesterday's incomplete batch.

Run with --dry-run (default) to review before writing anything.
"""

import argparse
import subprocess
from pathlib import Path

FOLDER = Path("/mnt/storage_sata/Chesterfield House")
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".avi", ".gif"}

DATE = "2004:05:07 12:00:00"
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
            print(f"  {f.name} -> date={DATE}, lat={LAT}, lon={LON}")
        print(f"\nRun again with --apply to write these {len(files)} corrections.")
        return

    updated = 0
    errors = 0
    for f in files:
        is_video = f.suffix.lower() in VIDEO_EXTENSIONS

        if is_video:
            cmd = [
                "exiftool", "-overwrite_original",
                f"-QuickTime:CreateDate={DATE}",
                f"-QuickTime:ModifyDate={DATE}",
                f"-XMP:GPSLatitude={LAT}", f"-XMP:GPSLongitude={LON}",
                str(f)
            ]
        else:
            lat_ref = "N" if LAT >= 0 else "S"
            lon_ref = "E" if LON >= 0 else "W"
            cmd = [
                "exiftool", "-overwrite_original",
                f"-DateTimeOriginal={DATE}", f"-CreateDate={DATE}",
                f"-GPSLatitude={abs(LAT)}", f"-GPSLatitudeRef={lat_ref}",
                f"-GPSLongitude={abs(LON)}", f"-GPSLongitudeRef={lon_ref}",
                str(f)
            ]

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
