"""
Ad-hoc GPS correction tool - for fixing specific individual files whose
GPS coordinates are known to be wrong. Handles both photos (standard EXIF
GPS tags) and videos (XMP GPS tags, which use signed values directly
instead of separate Ref fields).
"""

import argparse
import subprocess
from pathlib import Path

PHOTOS_IMPORT_CONTAINER = "/usr/src/app/external/photos-import"
PHOTOS_IMPORT_HOST = Path("/mnt/storage_sata/photos-import")

CORRECTIONS = [
    ("/usr/src/app/external/photos-import/2021 Pics and Videos/20210624_122507.mp4",
     63.749325, -148.9086, "Longitude sign error - Denali, Alaska"),
    ("/usr/src/app/external/photos-import/2021 Pics and Videos/2021_06_24 Alaska Trip/2021_06_25 (1).mp4",
     64.859178, -147.701478, "Longitude sign error - Fairbanks, Alaska"),
    ("/usr/src/app/external/photos-import/2021 Pics and Videos/20210625_133617.mp4",
     64.859178, -147.701478, "Longitude sign error - Fairbanks, Alaska"),
    ("/usr/src/app/external/photos-import/2021 Pics and Videos/20210624_122530.mp4",
     63.749325, -148.9086, "Longitude sign error - Denali, Alaska"),
    ("/usr/src/app/external/photos-import/2021 Pics and Videos/2021_06_24 Alaska Trip/2021_06_24 (2).mp4",
     63.749325, -148.9086, "Longitude sign error - Denali, Alaska"),
    ("/usr/src/app/external/photos-import/2021 Pics and Videos/2021_06_24 Alaska Trip/2021_06_24 (1).mp4",
     63.749325, -148.9086, "Longitude sign error - Denali, Alaska"),
]


def container_path_to_host(container_path: str) -> Path:
    rel = container_path[len(PHOTOS_IMPORT_CONTAINER):].lstrip("/")
    return PHOTOS_IMPORT_HOST / rel


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    print(f"Corrections to apply: {len(CORRECTIONS)}")

    if not args.apply:
        print("\n--- DRY RUN ---")
        for container_path, lat, lon, reason in CORRECTIONS:
            host_path = container_path_to_host(container_path)
            exists = "EXISTS" if host_path.exists() else "MISSING"
            print(f"  [{exists}] {host_path}")
            print(f"    -> lat={lat}, lon={lon}")
            print(f"    Reason: {reason}")
        print("\nRun again with --apply to write these corrections.")
        return

    updated = 0
    errors = 0
    for container_path, lat, lon, reason in CORRECTIONS:
        host_path = container_path_to_host(container_path)
        if not host_path.exists():
            print(f"  SKIP (file not found): {host_path}")
            errors += 1
            continue

        is_video = host_path.suffix.lower() in (".mp4", ".mov", ".m4v", ".avi")

        if is_video:
            cmd = [
                "exiftool", "-overwrite_original",
                f"-XMP:GPSLatitude={lat}", f"-XMP:GPSLongitude={lon}",
                str(host_path)
            ]
        else:
            lat_ref = "N" if lat >= 0 else "S"
            lon_ref = "E" if lon >= 0 else "W"
            cmd = [
                "exiftool", "-overwrite_original",
                f"-GPSLatitude={abs(lat)}", f"-GPSLatitudeRef={lat_ref}",
                f"-GPSLongitude={abs(lon)}", f"-GPSLongitudeRef={lon_ref}",
                str(host_path)
            ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            print(f"  ERROR on {host_path}: {result.stderr.strip()}")
            errors += 1
            continue

        print(f"  Updated ({'video/XMP' if is_video else 'photo/EXIF'}): {host_path}")
        updated += 1

    print(f"\nUpdated: {updated}")
    print(f"Errors: {errors}")
    print("\nNext: trigger a rescan of the External Library in Immich.")


if __name__ == "__main__":
    main()
