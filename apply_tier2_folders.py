"""
Tier 2 (folder-name based): apply GPS coordinates to files based on the
confirmed place names for each named subfolder.
"""

import argparse
import json
import re
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path

PHOTOS_IMPORT_CONTAINER = "/usr/src/app/external/photos-import"
PHOTOS_IMPORT_HOST = Path("/mnt/storage_sata/photos-import")
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".avi", ".gif"}

GENERIC_PATTERNS = [
    r"^\d{4}( - \d{4})? Pics and Videos$",
    r"^Immich Phone Import$",
    r"^Google Photos Import$",
    r"^Chargers\b",
    r"^DVD$",
    r"^Original Files$",
    r"^High Resolution$",
    r"^Items for Sale",
    r"^Share$",
    r"^SHARE$",
]
GENERIC_RE = re.compile("|".join(GENERIC_PATTERNS), re.IGNORECASE)

GEOCODE_CACHE_PATH = Path("/mnt/storage_sata/tier2_geocode_cache.json")


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
        "q": place_name,
        "format": "json",
        "limit": 1,
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

    with open("/home/blowe/langchain-projects/folder_to_place.json") as f:
        folder_to_place = json.load(f)

    unique_places = sorted(set(folder_to_place.values()))
    print(f"Unique place names to geocode: {len(unique_places)}")

    cache = load_geocode_cache()
    geocode_results = {}
    failed_places = []

    for i, place in enumerate(unique_places, 1):
        result = geocode_place(place, cache)
        geocode_results[place] = result
        if result is None:
            failed_places.append(place)
        if i % 10 == 0:
            save_geocode_cache(cache)
            print(f"  ...geocoded {i}/{len(unique_places)}")

    save_geocode_cache(cache)

    print(f"\nSuccessfully geocoded: {len(unique_places) - len(failed_places)}")
    print(f"Failed to geocode: {len(failed_places)}")
    if failed_places:
        print("Failed places (need manual coordinates or correction):")
        for p in failed_places:
            print(f"  - {p}")

    print("\nFetching Tier 2 candidate files...")
    query = """
        WITH daily_status AS (
            SELECT DATE(a."localDateTime") AS photo_date,
                   BOOL_OR(ae.latitude IS NOT NULL) AS day_has_any_gps
            FROM asset a
            LEFT JOIN asset_exif ae ON a.id = ae."assetId"
            WHERE a.status = 'active' AND a.visibility = 'timeline'
            GROUP BY DATE(a."localDateTime")
        )
        SELECT a."originalPath"
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
        path = line.strip()
        if not path:
            continue
        parts = Path(path).parts[:-1]
        relevant_parts = [
            p for p in parts
            if "photos-import" not in p and p not in ("/", "usr", "src", "app", "external")
        ]
        non_generic = [p for p in relevant_parts if not GENERIC_RE.match(p)]
        if not non_generic:
            continue
        deepest = non_generic[-1]
        if deepest in folder_to_place:
            place = folder_to_place[deepest]
            geo = geocode_results.get(place)
            if geo is not None:
                plan.append((path, place, geo["lat"], geo["lon"]))

    print(f"\nFiles that would receive GPS from confirmed folder locations: {len(plan)}")

    if not args.apply:
        print("\n--- DRY RUN: first 20 examples ---")
        for path, place, lat, lon in plan[:20]:
            print(f"  {path}")
            print(f"    -> {place}: lat={lat}, lon={lon}")
        print(f"\nRun again with --apply to write these {len(plan)} GPS updates.")
        return

    updated = 0
    errors = 0
    for i, (container_path, place, lat, lon) in enumerate(plan, 1):
        host_path = container_path_to_host(container_path)
        if not host_path.exists():
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
