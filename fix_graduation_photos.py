"""
Fix for 8 graduation photos with incorrect date and location.
Root cause: these photos had a wrong date in their original EXIF (showing
July 3, 2023), which caused Tier 1 to propagate an unrelated California
trip's real GPS onto them. Corrected using a verified-good reference photo
from the same graduation event.
"""

import subprocess
from pathlib import Path

PHOTOS_IMPORT_HOST = Path("/mnt/storage_sata/photos-import")

# From the verified-good reference photo (20230609_204919.jpg)
CORRECT_DATE = "2023:06:09 20:49:19"
CORRECT_LAT = 42.565300  # 42 deg 33' 55.08" N
CORRECT_LON = -82.984178  # 82 deg 59' 3.04" W

FILES = [
    "2023 Pics and Videos/20230703_164028685_iOS.jpg",
    "2023 Pics and Videos/20230703_164001018_iOS.jpg",
    "2023 Pics and Videos/20230703_164054761_iOS.jpg",
    "2023 Pics and Videos/20230703_163926497_iOS.jpg",
    "2023 Pics and Videos/20230703_163832283_iOS.jpg",
    "2023 Pics and Videos/20230703_163529773_iOS.jpg",
    "2023 Pics and Videos/20230703_163418970_iOS.jpg",
    "2023 Pics and Videos/20230703_163322061_iOS.jpg",
]

lat_ref = "N" if CORRECT_LAT >= 0 else "S"
lon_ref = "E" if CORRECT_LON >= 0 else "W"

updated = 0
errors = 0
for rel_path in FILES:
    host_path = PHOTOS_IMPORT_HOST / rel_path
    if not host_path.exists():
        print(f"  SKIP (not found): {host_path}")
        errors += 1
        continue

    result = subprocess.run(
        [
            "exiftool", "-overwrite_original",
            f"-DateTimeOriginal={CORRECT_DATE}",
            f"-CreateDate={CORRECT_DATE}",
            f"-GPSLatitude={abs(CORRECT_LAT)}", f"-GPSLatitudeRef={lat_ref}",
            f"-GPSLongitude={abs(CORRECT_LON)}", f"-GPSLongitudeRef={lon_ref}",
            str(host_path)
        ],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0:
        print(f"  ERROR on {host_path}: {result.stderr.strip()}")
        errors += 1
        continue

    print(f"  Updated: {host_path}")
    updated += 1

print(f"\nUpdated: {updated}")
print(f"Errors: {errors}")
