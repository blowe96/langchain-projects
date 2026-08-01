"""
Extract unique folder names appearing in the paths of GPS-less photos
(the Tier 2 candidate pool), sorted by impact, to identify real place names.
"""

import subprocess
from collections import Counter
from pathlib import Path


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

    folder_counter = Counter()
    total_files = 0

    for line in raw.strip().split("\n"):
        path = line.strip()
        if not path:
            continue
        total_files += 1
        parts = Path(path).parts
        for part in parts[:-1]:
            if "photos-import" in part or part in ("/", "usr", "src", "app", "external"):
                continue
            folder_counter[part] += 1

    print(f"Total Tier 2 candidate files: {total_files}")
    print(f"Unique folder names found: {len(folder_counter)}")
    print("\nFolder names sorted by file count (most impactful first):\n")

    for folder, count in folder_counter.most_common(150):
        print(f"  {count:6d}  {folder}")


if __name__ == "__main__":
    main()
