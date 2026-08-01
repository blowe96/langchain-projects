"""
Count actual FILES (not folder occurrences) among the Tier 2 candidate pool
that sit inside a specific, named event/trip subfolder.
"""

import subprocess
import re
from pathlib import Path

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

    total = 0
    has_specific_folder = 0

    for line in raw.strip().split("\n"):
        path = line.strip()
        if not path:
            continue
        total += 1
        parts = Path(path).parts[:-1]
        relevant_parts = [
            p for p in parts
            if "photos-import" not in p and p not in ("/", "usr", "src", "app", "external")
        ]
        if any(not GENERIC_RE.match(p) for p in relevant_parts):
            has_specific_folder += 1

    print(f"Total Tier 2 candidate files: {total}")
    print(f"Files with a specific, non-generic named subfolder: {has_specific_folder}")
    print(f"Files WITHOUT a specific named subfolder (loose in year folder): {total - has_specific_folder}")
    print(f"\nPercentage potentially coverable by folder-name matching: {has_specific_folder/total*100:.1f}%")


if __name__ == "__main__":
    main()
