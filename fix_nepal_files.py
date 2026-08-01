"""
Correction for files incorrectly showing "Nepal" as their location.
"""

import argparse
import subprocess
from pathlib import Path

PHOTOS_IMPORT_HOST = Path("/mnt/storage_sata/photos-import")
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".avi"}

BRIGHTON_MI = (42.5286, -83.7805)
DETROIT_MI = (42.3314, -83.0458)
CLEVELAND_OH = (41.4993, -81.6944)

CORRECTIONS = [
    ("2021 Pics and Videos/20211228_171927.mp4", BRIGHTON_MI),
    ("2021 Pics and Videos/20211228_172451.mp4", BRIGHTON_MI),
    ("2021 Pics and Videos/20211228_173048.mp4", BRIGHTON_MI),
    ("2021 Pics and Videos/20211228_173055.mp4", BRIGHTON_MI),
    ("2021 Pics and Videos/20211228_173106.mp4", BRIGHTON_MI),
    ("2021 Pics and Videos/20211228_174020.mp4", BRIGHTON_MI),
    ("2021 Pics and Videos/20211228_174753.mp4", BRIGHTON_MI),
    ("2021 Pics and Videos/20211228_175352.mp4", BRIGHTON_MI),
    ("2021 Pics and Videos/20211228_175823.mp4", BRIGHTON_MI),
    ("2021 Pics and Videos/20211228_180035.mp4", BRIGHTON_MI),
    ("2021 Pics and Videos/20211228_180550.mp4", BRIGHTON_MI),
    ("2021 Pics and Videos/2021_12_28 QB1 Selection/2021_12_28 QB1 Selection (1).mp4", BRIGHTON_MI),
    ("2021 Pics and Videos/2021_12_28 QB1 Selection/2021_12_28 QB1 Selection (2).mp4", BRIGHTON_MI),
    ("2021 Pics and Videos/2021_12_28 QB1 Selection/2021_12_28 QB1 Selection (3).mp4", BRIGHTON_MI),
    ("2021 Pics and Videos/2021_12_28 QB1 Selection/2021_12_28 QB1 Selection (4).mp4", BRIGHTON_MI),
    ("2021 Pics and Videos/2021_12_28 QB1 Selection/2021_12_28 QB1 Selection (5).mp4", BRIGHTON_MI),
    ("2021 Pics and Videos/2021_12_28 QB1 Selection/2021_12_28 QB1 Selection (6).mp4", BRIGHTON_MI),
    ("2021 Pics and Videos/2021_12_28 QB1 Selection/2021_12_28 QB1 Selection (7).mp4", BRIGHTON_MI),
    ("2021 Pics and Videos/2021_12_28 QB1 Selection/2021_12_28 QB1 Selection (8).mp4", BRIGHTON_MI),
    ("2021 Pics and Videos/2021_12_28 QB1 Selection/2021_12_28 QB1 Selection (9).mp4", BRIGHTON_MI),
    ("2021 Pics and Videos/20211229_173230123_iOS.heic", DETROIT_MI),
    ("2021 Pics and Videos/20211229_181147108_iOS.heic", DETROIT_MI),
    ("2021 Pics and Videos/20211229_210630000_iOS.jpg", DETROIT_MI),
    ("2021 Pics and Videos/20211229_222407000_iOS.jpg", DETROIT_MI),
    ("2021 Pics and Videos/20211229_222415000_iOS.jpg", DETROIT_MI),
    ("2021 Pics and Videos/20211229_231027000_iOS.jpg", DETROIT_MI),
    ("2021 Pics and Videos/20211229_231034000_iOS.jpg", DETROIT_MI),
    ("2021 Pics and Videos/20211230_034401000_iOS.jpg", DETROIT_MI),
    ("2021 Pics and Videos/20211230_034430000_iOS.jpg", DETROIT_MI),
    ("2021 Pics and Videos/20211230_041101000_iOS.jpg", DETROIT_MI),
    ("2021 Pics and Videos/20211230_041637000_iOS.jpg", DETROIT_MI),
    ("2021 Pics and Videos/20211230_002419458_iOS.jpg", CLEVELAND_OH),
    ("2024 Pics and Videos/20240328_050747000_iOS.MOV", CLEVELAND_OH),
    ("2024 Pics and Videos/20240328_050749000_iOS.MOV", CLEVELAND_OH),
    ("2024 Pics and Videos/Immich Phone Import/cm-chat-media-video-1:9aa24422-7113-5d0f-a70b-80b50674b61f:2766:1:0.mov", CLEVELAND_OH),
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    print(f"Corrections to apply: {len(CORRECTIONS)}")

    if not args.apply:
        print("\n--- DRY RUN ---")
        for rel_path, (lat, lon) in CORRECTIONS:
            host_path = PHOTOS_IMPORT_HOST / rel_path
            exists = "EXISTS" if host_path.exists() else "MISSING"
            print(f"  [{exists}] {rel_path} -> lat={lat}, lon={lon}")
        print(f"\nRun again with --apply to write these {len(CORRECTIONS)} corrections.")
        return

    updated = 0
    errors = 0
    for rel_path, (lat, lon) in CORRECTIONS:
        host_path = PHOTOS_IMPORT_HOST / rel_path
        if not host_path.exists():
            print(f"  SKIP (not found): {host_path}")
            errors += 1
            continue

        is_video = host_path.suffix.lower() in VIDEO_EXTENSIONS

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

        print(f"  Updated: {host_path}")
        updated += 1

    print(f"\nUpdated: {updated}")
    print(f"Errors: {errors}")
    print("\nNext: trigger a rescan of the External Library in Immich.")


if __name__ == "__main__":
    main()
