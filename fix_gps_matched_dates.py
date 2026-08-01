"""
Fix for photos with real GPS but no date, where a prior assessment
confirmed a HIGH-confidence match (nearby dated photos cluster within a
narrow 0-14 day window - a genuine one-time location, not a recurring
spot like home). Uses the single geographically closest dated reference
photo's exact date/time.

Run with --dry-run (default) to review before writing anything.
"""

import argparse
import subprocess
import math
from pathlib import Path

PHOTOS_IMPORT_CONTAINER = "/usr/src/app/external/photos-import"
PHOTOS_IMPORT_HOST = Path("/mnt/storage_sata/photos-import")

# Files confirmed HIGH confidence from the assessment
HIGH_CONFIDENCE_FILES = [
    "2017 Pics and Videos/IMG_1423.JPG",
    "2017 Pics and Videos/IMG_1424.JPG",
    "2017 Pics and Videos/IMG_1716.JPG",
    "2018 Pics and Videos/IMG_1155.JPG",
    "2018 Pics and Videos/IMG_1212.JPG",
    "2018 Pics and Videos/IMG_1224.JPG",
    "2018 Pics and Videos/IMG_1430.JPG",
    "2018 Pics and Videos/IMG_1674.JPG",
    "2018 Pics and Videos/IMG_1675.JPG",
    "2018 Pics and Videos/IMG_1717.JPG",
    "2018 Pics and Videos/IMG_1723.JPG",
    "2018 Pics and Videos/IMG_1797.JPG",
    "2018 Pics and Videos/IMG_1857.JPG",
    "2018 Pics and Videos/IMG_1942.JPG",
    "2018 Pics and Videos/IMG_2048.JPG",
    "2018 Pics and Videos/IMG_2051.JPG",
    "2018 Pics and Videos/IMG_2152.JPG",
    "2018 Pics and Videos/IMG_2155.JPG",
    "2018 Pics and Videos/IMG_2632.JPG",
    "2018 Pics and Videos/IMG_2889.JPG",
    "2018 Pics and Videos/IMG_2890.JPG",
    "2019 Pics and Videos/2019_12_28 Chicago Trip/2019_12_28 (3).jpg",
    "2024 Pics and Videos/IMG_0735.HEIC",
    "2024 Pics and Videos/IMG_4582.JPG",
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


def get_gps(host_path: Path):
    result = subprocess.run(
        ["exiftool", "-s3", "-GPSLatitude#", "-GPSLongitude#", str(host_path)],
        capture_output=True, text=True, timeout=15
    )
    lines = result.stdout.strip().split("\n")
    if len(lines) != 2 or not lines[0] or not lines[1]:
        return None
    try:
        return float(lines[0]), float(lines[1])
    except ValueError:
        return None


def haversine_meters(lat1, lon1, lat2, lon2):
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return R * 2 * math.asin(math.sqrt(a))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    print("Fetching dated, GPS-tagged reference assets...")
    query = """
        SELECT a."localDateTime", ae.latitude, ae.longitude
        FROM asset a
        JOIN asset_exif ae ON a.id = ae."assetId"
        WHERE a.status = 'active' AND a.visibility = 'timeline'
        AND ae.latitude IS NOT NULL
        AND a."localDateTime" < '2026-07-24';
    """
    raw = run_psql(query)
    references = []
    for line in raw.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        dt, lat, lon = parts
        references.append((dt, float(lat), float(lon)))
    print(f"Reference pool: {len(references)} assets")

    plan = []
    for rel_path in HIGH_CONFIDENCE_FILES:
        host_path = PHOTOS_IMPORT_HOST / rel_path
        if not host_path.exists():
            print(f"  SKIP (not found): {host_path}")
            continue
        gps = get_gps(host_path)
        if gps is None:
            print(f"  SKIP (no GPS): {host_path}")
            continue
        lat, lon = gps

        best_dt = None
        best_dist = None
        for dt, rlat, rlon in references:
            dist = haversine_meters(lat, lon, rlat, rlon)
            if best_dist is None or dist < best_dist:
                best_dist = dist
                best_dt = dt

        if best_dt is None:
            print(f"  SKIP (no match found): {host_path}")
            continue

        exif_date = best_dt[:19].replace("-", ":", 2).replace("T", " ")
        plan.append((host_path, exif_date, best_dist))

    print(f"\nFiles to correct: {len(plan)}")

    if not args.apply:
        print("\n--- DRY RUN ---")
        for host_path, exif_date, dist in plan:
            print(f"  {host_path.name} -> {exif_date} (nearest match {dist:.0f}m away)")
        print(f"\nRun again with --apply to write these {len(plan)} date corrections.")
        return

    updated = 0
    errors = 0
    for host_path, exif_date, dist in plan:
        result = subprocess.run(
            [
                "exiftool", "-overwrite_original",
                f"-DateTimeOriginal={exif_date}",
                f"-CreateDate={exif_date}",
                str(host_path)
            ],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            print(f"  ERROR on {host_path}: {result.stderr.strip()}")
            errors += 1
            continue
        updated += 1

    print(f"\nUpdated: {updated}")
    print(f"Errors: {errors}")


if __name__ == "__main__":
    main()
