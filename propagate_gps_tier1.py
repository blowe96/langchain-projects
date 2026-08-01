"""
Tier 1: Propagate real GPS coordinates to GPS-less photos, using the
nearest-in-time GPS-tagged photo from the SAME calendar day as the source.
"""

import argparse
import subprocess
from collections import defaultdict
from datetime import datetime
from pathlib import Path

PHOTOS_IMPORT_CONTAINER = "/usr/src/app/external/photos-import"
PHOTOS_IMPORT_HOST = Path("/mnt/storage_sata/photos-import")


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

    print("Fetching all active timeline assets with date/GPS info...")
    query = """
        SELECT a.id, a."originalPath", a."localDateTime", ae.latitude, ae.longitude
        FROM asset a
        LEFT JOIN asset_exif ae ON a.id = ae."assetId"
        WHERE a.status = 'active' AND a.visibility = 'timeline';
    """
    raw = run_psql(query)

    rows = []
    for line in raw.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) != 5:
            continue
        asset_id, path, local_dt, lat, lon = parts
        rows.append({
            "id": asset_id,
            "path": path,
            "dt": local_dt,
            "lat": float(lat) if lat not in ("", "\\N") else None,
            "lon": float(lon) if lon not in ("", "\\N") else None,
        })

    print(f"Total assets: {len(rows)}")

    by_day = defaultdict(list)
    for r in rows:
        day = r["dt"][:10]
        by_day[day].append(r)

    plan = []
    for day, items in by_day.items():
        gps_items = [r for r in items if r["lat"] is not None]
        no_gps_items = [r for r in items if r["lat"] is None]
        if not gps_items or not no_gps_items:
            continue

        for target in no_gps_items:
            target_time = datetime.fromisoformat(target["dt"].replace("Z", "+00:00"))
            best = None
            best_diff = None
            for source in gps_items:
                source_time = datetime.fromisoformat(source["dt"].replace("Z", "+00:00"))
                diff = abs((target_time - source_time).total_seconds())
                if best_diff is None or diff < best_diff:
                    best = source
                    best_diff = diff
            plan.append((target, best, best_diff))

    print(f"\nFiles that would receive propagated GPS coordinates: {len(plan)}")

    if not args.apply:
        print("\n--- DRY RUN: first 15 examples ---")
        for target, source, diff in plan[:15]:
            hours = diff / 3600
            print(f"  {target['path']}")
            print(f"    -> lat={source['lat']:.5f}, lon={source['lon']:.5f} (from photo {hours:.1f}h away same day)")
        print(f"\nRun again with --apply to write these {len(plan)} GPS updates to actual files.")
        return

    print("\nApplying GPS updates...")
    updated = 0
    errors = 0
    for i, (target, source, diff) in enumerate(plan, 1):
        host_path = container_path_to_host(target["path"])
        if not host_path.exists():
            errors += 1
            continue

        lat = source["lat"]
        lon = source["lon"]
        lat_ref = "N" if lat >= 0 else "S"
        lon_ref = "E" if lon >= 0 else "W"

        try:
            result = subprocess.run(
                [
                    "exiftool", "-overwrite_original",
                    f"-GPSLatitude={abs(lat)}", f"-GPSLatitudeRef={lat_ref}",
                    f"-GPSLongitude={abs(lon)}", f"-GPSLongitudeRef={lon_ref}",
                    str(host_path)
                ],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode != 0:
                print(f"  Error on {host_path}: {result.stderr.strip()}")
                errors += 1
                continue
            updated += 1
        except Exception as e:
            print(f"  Error on {host_path}: {e}")
            errors += 1

        if i % 500 == 0:
            print(f"  ...processed {i}/{len(plan)}")

    print(f"\nUpdated: {updated}")
    print(f"Errors: {errors}")
    print("\nNext: trigger a rescan of the External Library in Immich so it re-reads")
    print("the updated EXIF data and reverse-geocodes the new locations.")


if __name__ == "__main__":
    main()
