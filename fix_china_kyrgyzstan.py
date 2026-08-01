"""
Comprehensive fix for the Tier 1 video GPS longitude sign bug - fixes all
videos currently flagged as China or Kyrgyzstan (confirmed impossible).
"""

import argparse
import subprocess
from pathlib import Path

PHOTOS_IMPORT_CONTAINER = "/usr/src/app/external/photos-import"
PHOTOS_IMPORT_HOST = Path("/mnt/storage_sata/photos-import")
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".avi", ".gif"}


def run_psql(query: str) -> str:
    result = subprocess.run(
        ["docker", "exec", "-i", "immich_postgres", "psql", "-U", "postgres", "-d", "immich",
         "-t", "-A", "-F", "\t"],
        input=query, capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"psql error: {result.stderr}")
    return result.stdout


def container_path_to_host(container_path: str) -> Path:
    rel = container_path[len(PHOTOS_IMPORT_CONTAINER):].lstrip("/")
    return PHOTOS_IMPORT_HOST / rel


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    print("Fetching all videos flagged as China or Kyrgyzstan...")
    query = """
        SELECT a."originalPath", ae.latitude, ae.longitude
        FROM asset a
        JOIN asset_exif ae ON a.id = ae."assetId"
        WHERE a.status = 'active'
        AND ae.country IN ('People''s Republic of China', 'Kyrgyzstan');
    """
    raw = run_psql(query)

    rows = []
    for line in raw.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        path, lat, lon = parts
        rows.append((path, float(lat), float(lon)))

    print(f"Total files found: {len(rows)}")

    if not args.apply:
        print("\n--- DRY RUN: first 15 examples ---")
        for path, lat, lon in rows[:15]:
            print(f"  {path}")
            print(f"    current lon={lon} -> corrected lon={-lon} (lat unchanged: {lat})")
        print(f"\nRun again with --apply to correct all {len(rows)} files.")
        return

    updated = 0
    errors = 0
    for i, (container_path, lat, lon) in enumerate(rows, 1):
        host_path = container_path_to_host(container_path)
        if not host_path.exists():
            print(f"  SKIP (not found): {host_path}")
            errors += 1
            continue

        corrected_lon = -lon
        is_video = host_path.suffix.lower() in VIDEO_EXTENSIONS

        if is_video:
            cmd = [
                "exiftool", "-overwrite_original",
                f"-XMP:GPSLatitude={lat}", f"-XMP:GPSLongitude={corrected_lon}",
                str(host_path)
            ]
        else:
            lat_ref = "N" if lat >= 0 else "S"
            lon_ref = "E" if corrected_lon >= 0 else "W"
            cmd = [
                "exiftool", "-overwrite_original",
                f"-GPSLatitude={abs(lat)}", f"-GPSLatitudeRef={lat_ref}",
                f"-GPSLongitude={abs(corrected_lon)}", f"-GPSLongitudeRef={lon_ref}",
                str(host_path)
            ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            print(f"  ERROR on {host_path}: {result.stderr.strip()}")
            errors += 1
            continue

        updated += 1
        if i % 200 == 0:
            print(f"  ...processed {i}/{len(rows)} (updated: {updated}, errors: {errors})")

    print(f"\nUpdated: {updated}")
    print(f"Errors: {errors}")
    print("\nNext: trigger a rescan of the External Library in Immich.")


if __name__ == "__main__":
    main()
