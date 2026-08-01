"""
Audit script: re-derive what Tier 1 SHOULD have written for every video
file, and compare against what's actually currently stored, flagging
hemisphere sign mismatches.
"""

import subprocess
from collections import defaultdict
from datetime import datetime
from pathlib import Path

VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".avi", ".mts"}


def run_psql(query: str) -> str:
    result = subprocess.run(
        ["docker", "exec", "-i", "immich_postgres", "psql", "-U", "postgres", "-d", "immich",
         "-t", "-A", "-F", "\t"],
        input=query, capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"psql error: {result.stderr}")
    return result.stdout


def main():
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

    mismatches = []
    checked = 0

    for day, items in by_day.items():
        trustworthy_sources = [
            r for r in items
            if r["lat"] is not None and Path(r["path"]).suffix.lower() not in VIDEO_EXTENSIONS
        ]
        videos_with_gps = [
            r for r in items
            if r["lat"] is not None and Path(r["path"]).suffix.lower() in VIDEO_EXTENSIONS
        ]

        if not trustworthy_sources or not videos_with_gps:
            continue

        for video in videos_with_gps:
            checked += 1
            video_time = datetime.fromisoformat(video["dt"].replace("Z", "+00:00"))
            best_source = None
            best_diff = None
            for source in trustworthy_sources:
                source_time = datetime.fromisoformat(source["dt"].replace("Z", "+00:00"))
                diff = abs((video_time - source_time).total_seconds())
                if best_diff is None or diff < best_diff:
                    best_source = source
                    best_diff = diff

            correct_lat = best_source["lat"]
            correct_lon = best_source["lon"]
            stored_lat = video["lat"]
            stored_lon = video["lon"]

            lat_sign_wrong = (correct_lat >= 0) != (stored_lat >= 0) and abs(correct_lat) > 0.01
            lon_sign_wrong = (correct_lon >= 0) != (stored_lon >= 0) and abs(correct_lon) > 0.01

            lat_magnitude_close = abs(abs(correct_lat) - abs(stored_lat)) < 1.0
            lon_magnitude_close = abs(abs(correct_lon) - abs(stored_lon)) < 1.0

            if (lat_sign_wrong and lat_magnitude_close) or (lon_sign_wrong and lon_magnitude_close):
                mismatches.append({
                    "path": video["path"],
                    "stored_lat": stored_lat,
                    "stored_lon": stored_lon,
                    "correct_lat": correct_lat,
                    "correct_lon": correct_lon,
                    "source_path": best_source["path"],
                    "time_diff_hours": best_diff / 3600,
                })

    print(f"\nVideo files with GPS checked: {checked}")
    print(f"Suspected hemisphere sign errors found: {len(mismatches)}")

    with open("/mnt/storage_sata/video_gps_audit.txt", "w") as f:
        f.write(f"VIDEO GPS HEMISPHERE SIGN AUDIT - {len(mismatches)} suspected errors\n")
        f.write("=" * 80 + "\n\n")
        for m in mismatches:
            f.write(f"File: {m['path']}\n")
            f.write(f"  Currently stored: lat={m['stored_lat']}, lon={m['stored_lon']}\n")
            f.write(f"  Should be:        lat={m['correct_lat']}, lon={m['correct_lon']}\n")
            f.write(f"  Source: {m['source_path']} ({m['time_diff_hours']:.1f}h away same day)\n\n")

    print(f"Full report written to: /mnt/storage_sata/video_gps_audit.txt")


if __name__ == "__main__":
    main()
