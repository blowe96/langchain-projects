"""
For each Tier 2 candidate file, identify its DEEPEST non-generic folder,
and count files per unique folder without double-counting.
"""

import subprocess
import re
from pathlib import Path
from collections import defaultdict

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

    folder_counts = defaultdict(int)
    folder_examples = {}
    loose_in_year_folder = 0

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
        if non_generic:
            deepest = non_generic[-1]
            folder_counts[deepest] += 1
            if deepest not in folder_examples:
                folder_examples[deepest] = path
        else:
            loose_in_year_folder += 1

    print(f"Files loose in year folder (no specific subfolder): {loose_in_year_folder}", flush=True)

    with open("/mnt/storage_sata/folder_mapping_data.txt", "w") as f:
        for folder, count in sorted(folder_counts.items(), key=lambda x: -x[1]):
            example = folder_examples[folder]
            f.write(f"{folder}|{count}|{example}\n")

    print(f"Unique specific folders: {len(folder_counts)}")
    print(f"Total files in specific folders: {sum(folder_counts.values())}")
    print("Data written to /mnt/storage_sata/folder_mapping_data.txt")


if __name__ == "__main__":
    main()
