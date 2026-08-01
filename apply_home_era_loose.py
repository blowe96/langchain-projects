"""
Assign home-address GPS to "loose" files (no event folder, no same-day
GPS anchor) based on the user's confirmed home-era date ranges.

Run with --dry-run (default) to review geocoding results and the file
count before writing anything.
"""

import argparse
import json
import subprocess
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

PHOTOS_IMPORT_CONTAINER = "/usr/src/app/external/photos-import"
PHOTOS_IMPORT_HOST = Path("/mnt/storage_sata/photos-import")
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".avi", ".gif"}
GEOCODE_CACHE_PATH = Path("/mnt/storage_sata/tier2_geocode_cache.json")

# (start_date, end_date_exclusive, address, label)
HOME_ERAS = [
    ("2001-04-01", "2008-01-01", "11332 Aspen Drive, Plymouth, Michigan, USA", "Plymouth, MI"),
    ("2008-01-01", "2010-06-20", "Muskatli Utca, Budapest, Hungary", "Budapest, Hungary"),
    ("2010-06-20", "2012-06-24", "Kloppenheimer Strasse, Wiesbaden, Germany", "Wiesbaden, Germany"),
    ("2012-06-24", "2030-01-01", "52463 Indian Summer Drive, Chesterfield, Michigan, USA", "Chesterfield, MI"),
]


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


def load_geocode_cache():
    if GEOCODE_CACHE_PATH.exists():
        with open(GEOCODE_CACHE_PATH) as f:
            return json.load(f)
    return {}


def save_geocode_cache(cache):
    with open(GEOCODE_CACHE_PATH, "w") as f:
        json.dump(cache, f, indent=2)


def geocode_place(place_name: str, cache: dict):
    if place_name in cache:
        return cache[place_name]
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode({
        "q": place_name, "format": "json", "limit": 1,
    })
    req = urllib.request.Request(url, headers={"User-Agent": "PhotoGPSTool/1.0 (personal use)"})
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            data = json.loads(response.read().decode())
        if not data:
            cache[place_name] = None
            return None
        result = {"lat": float(data[0]["lat"]), "lon": float(data[0]["lon"]), "display_name": data[0]["display_name"]}
        cache[place_name] = result
        return result
    except Exception as e:
        print(f"  Geocoding error for '{place_name}': {e}")
        cache[place_name] = None
        return None
    finally:
        time.sleep(1.1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    cache = load_geocode_cache()
    print("Geocoding home addresses...\n")
    geocoded_eras = []
    for start, end, address, label in HOME_ERAS:
        result = geocode_place(address, cache)
        if result is None:
            print(f"  FAILED to geocode: {address}")
            continue
        print(f"  {label}: {address}")
        print(f"    -> lat={result['lat']}, lon={result['lon']}")
        print(f"    -> Nominatim matched: {result['display_name']}")
        print()
        geocoded_eras.append((start, end, result["lat"], result["lon"], label))
    save_geocode_cache(cache)

    if len(geocoded_eras) != len(HOME_ERAS):
        print("Not all addresses geocoded successfully - stopping before proceeding further.")
        return

    print("Fetching loose Tier 2 candidate files (no folder match)...")
    query = """
        WITH daily_status AS (
            SELECT DATE(a."localDateTime") AS photo_date,
                   BOOL_OR(ae.latitude IS NOT NULL) AS day_has_any_gps
            FROM asset a
            LEFT JOIN asset_exif ae ON a.id = ae."assetId"
            WHERE a.status = 'active' AND a.visibility = 'timeline'
            GROUP BY DATE(a."localDateTime")
        )
        SELECT a."originalPath", a."localDateTime"
        FROM asset a
        LEFT JOIN asset_exif ae ON a.id = ae."assetId"
        JOIN daily_status ds ON ds.photo_date = DATE(a."localDateTime")
        WHERE a.status = 'active' AND a.visibility = 'timeline'
        AND ae.latitude IS NULL
        AND ds.day_has_any_gps = false
        AND ae.make IS NOT NULL AND ae.model IS NOT NULL
        AND a."originalFileName" !~* 'screenshot|screen shot|img_[0-9]+\\.png$';
    """
    raw = run_psql(query)

    plan = []
    for line in raw.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) != 2:
            continue
        path, local_dt = parts
        photo_date = local_dt[:10]
        for start, end, lat, lon, label in geocoded_eras:
            if start <= photo_date < end:
                plan.append((path, photo_date, lat, lon, label))
                break

    print(f"\nFiles that would receive a home-era GPS assignment: {len(plan)}")

    if not args.apply:
        print("\n--- DRY RUN: sample of 5 per era ---")
        shown = {}
        for path, date, lat, lon, label in plan:
            shown.setdefault(label, 0)
            if shown[label] < 5:
                print(f"  [{label}] {path} ({date}) -> lat={lat}, lon={lon}")
                shown[label] += 1
        print(f"\nRun again with --apply to write these {len(plan)} GPS updates.")
        return

    updated = 0
    errors = 0
    for i, (container_path, date, lat, lon, label) in enumerate(plan, 1):
        host_path = container_path_to_host(container_path)
        if not host_path.exists():
            errors += 1
            continue

        is_video = host_path.suffix.lower() in VIDEO_EXTENSIONS
        if is_video:
            cmd = ["exiftool", "-overwrite_original", f"-XMP:GPSLatitude={lat}", f"-XMP:GPSLongitude={lon}", str(host_path)]
        else:
            lat_ref = "N" if lat >= 0 else "S"
            lon_ref = "E" if lon >= 0 else "W"
            cmd = ["exiftool", "-overwrite_original",
                   f"-GPSLatitude={abs(lat)}", f"-GPSLatitudeRef={lat_ref}",
                   f"-GPSLongitude={abs(lon)}", f"-GPSLongitudeRef={lon_ref}", str(host_path)]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            errors += 1
            continue
        updated += 1
        if i % 500 == 0:
            print(f"  ...processed {i}/{len(plan)} (updated: {updated}, errors: {errors})")

    print(f"\nUpdated: {updated}")
    print(f"Errors: {errors}")
    print("\nNext: trigger a rescan of the External Library in Immich.")


if __name__ == "__main__":
    main()
