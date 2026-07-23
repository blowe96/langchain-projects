"""
Fix dates on the confirmed no-EXIF files, parsing the date from the iOS
filename pattern and converting from UTC to America/Detroit local time
before writing.
"""

import argparse
import re
import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

DB_PATH = Path("/mnt/storage_sata/photo_index.db")
CANDIDATES_FILE = Path("/mnt/storage_sata/no_exif_candidates.txt")

FILENAME_PATTERN = re.compile(r"^(\d{8})_(\d{9})_iOS\.\w+$", re.IGNORECASE)
LOCAL_TZ = ZoneInfo("America/Detroit")


def parse_ios_filename_utc(filename: str):
    match = FILENAME_PATTERN.match(filename)
    if not match:
        return None
    date_part, time_part = match.groups()
    try:
        year = int(date_part[0:4])
        month = int(date_part[4:6])
        day = int(date_part[6:8])
        hour = int(time_part[0:2])
        minute = int(time_part[2:4])
        second = int(time_part[4:6])
        dt_utc = datetime(year, month, day, hour, minute, second, tzinfo=ZoneInfo("UTC"))
        if dt_utc.year < 1995 or dt_utc > datetime.now(ZoneInfo("UTC")):
            return None
        return dt_utc
    except (ValueError, IndexError):
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    file_paths = [line.strip() for line in open(CANDIDATES_FILE) if line.strip()]
    print(f"Files to process: {len(file_paths)}")

    plan = []
    for file_path in file_paths:
        filename = Path(file_path).name
        dt_utc = parse_ios_filename_utc(filename)
        if not dt_utc:
            continue
        dt_local = dt_utc.astimezone(LOCAL_TZ)
        plan.append((file_path, dt_local))

    print(f"Successfully parsed: {len(plan)}")

    if args.dry_run:
        print("\n--- DRY RUN: first 20 examples ---")
        for file_path, dt_local in plan[:20]:
            print(f"  {file_path}")
            print(f"    -> {dt_local.strftime('%Y:%m:%d %H:%M:%S %Z')}")
        print(f"\nTotal that would be updated: {len(plan)}")
        return

    conn = sqlite3.connect(DB_PATH)
    updated = 0
    errors = 0

    for i, (file_path, dt_local) in enumerate(plan, 1):
        exif_str = dt_local.strftime("%Y:%m:%d %H:%M:%S")
        path = Path(file_path)
        if not path.exists():
            errors += 1
            continue
        try:
            result = subprocess.run(
                ["exiftool", "-overwrite_original", f"-DateTimeOriginal={exif_str}", str(path)],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode != 0:
                print(f"  Error on {path}: {result.stderr.strip()}")
                errors += 1
                continue
            conn.execute(
                "UPDATE files SET date_taken = ?, date_source = 'filename_pattern_utc_converted', updated_at = CURRENT_TIMESTAMP WHERE file_path = ?",
                (dt_local.isoformat(), file_path),
            )
            updated += 1
        except Exception as e:
            print(f"  Error on {path}: {e}")
            errors += 1

        if i % 100 == 0:
            conn.commit()
            print(f"  ...processed {i}/{len(plan)} (updated: {updated}, errors: {errors})")

    conn.commit()
    conn.close()
    print(f"\nDone. Updated: {updated}, Errors: {errors}")
    print("Next: rescan the External Library in Immich.")


if __name__ == "__main__":
    main()
