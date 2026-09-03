"""
Full deduplication check for the entire "Monicas Phone" folder (~4,971
files) against the whole photos-import archive. Uses file size as a
fast pre-filter before SHA-256 verification.

Read-only - reports results, makes no changes. A follow-up script will
handle the actual merge once we've reviewed these results.
"""

import hashlib
from pathlib import Path
from collections import defaultdict

MONICAS_PHONE = Path("/mnt/storage_sata/Monicas Phone")
PHOTOS_IMPORT = Path("/mnt/storage_sata/photos-import")


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def main():
    print("Scanning Monicas Phone folder...")
    monica_files = [f for f in MONICAS_PHONE.rglob("*") if f.is_file()]
    print(f"Total files in Monicas Phone: {len(monica_files)}")

    print("\nBuilding size index of photos-import archive...")
    size_index = defaultdict(list)
    archive_count = 0
    for f in PHOTOS_IMPORT.rglob("*"):
        if f.is_file():
            archive_count += 1
            size_index[f.stat().st_size].append(f)
    print(f"Archive total: {archive_count} files")

    already_present = []
    genuinely_new = []

    print(f"\nChecking all {len(monica_files)} files...")
    for i, mf in enumerate(monica_files, 1):
        mf_size = mf.stat().st_size
        candidates = size_index.get(mf_size, [])

        match = None
        if candidates:
            mf_hash = sha256_of(mf)
            for c in candidates:
                if sha256_of(c) == mf_hash:
                    match = c
                    break

        if match:
            already_present.append((mf, match))
        else:
            genuinely_new.append(mf)

        if i % 500 == 0:
            print(f"  ...checked {i}/{len(monica_files)}")

    print(f"\n=== FULL RESULTS ===")
    print(f"Total files: {len(monica_files)}")
    print(f"Already in archive (true duplicates): {len(already_present)}")
    print(f"Genuinely new: {len(genuinely_new)}")

    with open("/mnt/storage_sata/monica_phone_new_files.txt", "w") as f:
        for path in genuinely_new:
            f.write(f"{path}\n")
    print(f"\nList of genuinely new files written to: monica_phone_new_files.txt")

    with open("/mnt/storage_sata/monica_phone_duplicates.txt", "w") as f:
        for mf, match in already_present:
            f.write(f"{mf} -> already at {match}\n")
    print(f"List of confirmed duplicates written to: monica_phone_duplicates.txt")


if __name__ == "__main__":
    main()
