"""
Check which files (matching the iOS filename pattern with date_source='filesystem'
in our database) genuinely have NO EXIF date tags at all, versus files that
actually do have valid EXIF that our extraction script simply failed to read.
"""

import re
import sqlite3
import subprocess
from pathlib import Path

DB_PATH = Path("/mnt/storage_sata/photo_index.db")
FILENAME_PATTERN = re.compile(r"^(\d{8})_(\d{9})_iOS\.\w+$", re.IGNORECASE)


def has_real_exif_date(path: Path) -> bool:
    try:
        result = subprocess.run(
            ["exiftool", "-DateTimeOriginal", "-CreateDate", "-s3", str(path)],
            capture_output=True, text=True, timeout=15
        )
        output = result.stdout.strip()
        return bool(output)
    except Exception:
        return False


def main():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT id, file_path FROM files WHERE date_source = 'filesystem'"
    ).fetchall()
    conn.close()

    candidates = [
        (fid, fp) for fid, fp in rows if FILENAME_PATTERN.match(Path(fp).name)
    ]
    print(f"Total iOS-filename candidates to check: {len(candidates)}")

    no_exif = []
    has_exif = []

    for i, (file_id, file_path) in enumerate(candidates, 1):
        path = Path(file_path)
        if not path.exists():
            continue
        if has_real_exif_date(path):
            has_exif.append(file_path)
        else:
            no_exif.append(file_path)

        if i % 200 == 0:
            print(f"  ...checked {i}/{len(candidates)}")

    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)
    print(f"Files with genuinely NO EXIF date (safe for filename fix): {len(no_exif)}")
    print(f"Files with EXIF our script missed (already correct in Immich): {len(has_exif)}")

    with open("/mnt/storage_sata/no_exif_candidates.txt", "w") as f:
        for p in no_exif:
            f.write(p + "\n")
    print(f"\nList of true no-EXIF files written to: /mnt/storage_sata/no_exif_candidates.txt")


if __name__ == "__main__":
    main()
