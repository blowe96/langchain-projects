"""
Assessment (read-only) for photos with real GPS but no date: for each,
find nearby dated photos (within ~150 meters) and report the SPREAD of
dates found - a narrow spread (few days) means a confident one-time
location match; a wide spread (months/years) means this is likely a
recurring location (like home), where GPS proximity alone can't pinpoint
a specific date.

No files are modified - this is purely a report to inform next steps.
"""

import subprocess
import math
from pathlib import Path
from datetime import datetime

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
    with open("/mnt/storage_sata/no_date_99.txt") as f:
        candidate_lines = [l.strip() for l in f if l.strip().startswith("/usr/src/app")]

    print("Fetching all dated, GPS-tagged reference assets from the archive...")
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
    print(f"Reference pool: {len(references)} dated, GPS-tagged assets")

    print(f"\nAssessing {len(candidate_lines)} candidates...\n")

    for container_path in candidate_lines:
        host_path = container_path_to_host(container_path)
        if not host_path.exists():
            continue
        gps = get_gps(host_path)
        if gps is None:
            continue
        lat, lon = gps

        nearby_dates = []
        for dt, rlat, rlon in references:
            dist = haversine_meters(lat, lon, rlat, rlon)
            if dist <= 150:
                nearby_dates.append(dt)

        if not nearby_dates:
            print(f"{host_path.name}: NO nearby dated photos found within 150m")
            continue

        nearby_dates.sort()
        earliest = nearby_dates[0][:10]
        latest = nearby_dates[-1][:10]
        span_days = (datetime.fromisoformat(latest) - datetime.fromisoformat(earliest)).days

        confidence = "HIGH (narrow spread)" if span_days <= 14 else ("MEDIUM" if span_days <= 90 else "LOW (recurring location)")
        print(f"{host_path.name}: {len(nearby_dates)} nearby photos, spans {earliest} to {latest} ({span_days} days) - {confidence}")


if __name__ == "__main__":
    main()
