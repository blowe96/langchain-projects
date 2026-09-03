"""
Check a random sample of files from "Monicas Phone" against the entire
photos-import archive to see how many are already present (regardless
of filename or folder location).

Uses file size as a fast pre-filter (cheap - just a stat, no hashing)
before doing a SHA-256 comparison only on size-matched candidates -
much faster than hashing the entire ~84,000 file archive.

Read-only - makes no changes, just reports.
"""

import argparse
import hashlib
import random
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
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample-size", type=int, default=100)
    args = parser.parse_args()

    print("Scanning Monicas Phone folder...")
    monica_files = [f for f in MONICAS_PHONE.rglob("*") if f.is_file()]
    print(f"Total files in Monicas Phone: {len(monica_files)}")

    sample = random.sample(monica_files, min(args.sample_size, len(monica_files)))
    print(f"Checking a random sample of {len(sample)} files...")

    print("\nBuilding size index of photos-import archive (fast, no hashing yet)...")
    size_index = defaultdict(list)
    archive_count = 0
    for f in PHOTOS_IMPORT.rglob("*"):
        if f.is_file():
            archive_count += 1
            size_index[f.stat().st_size].append(f)
    print(f"Archive total: {archive_count} files")

    found = 0
    not_found = 0
    not_found_examples = []

    for i, mf in enumerate(sample, 1):
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
            found += 1
        else:
            not_found += 1
            not_found_examples.append(mf)

        if i % 20 == 0:
            print(f"  ...checked {i}/{len(sample)}")

    print(f"\n=== RESULTS ===")
    print(f"Sample size: {len(sample)}")
    print(f"Already in archive (confirmed match): {found}")
    print(f"NOT found in archive: {not_found}")
    print(f"Estimated % already present: {found/len(sample)*100:.1f}%")

    if not_found_examples:
        print(f"\nSample of files NOT found in archive:")
        for f in not_found_examples[:15]:
            print(f"  {f}")


if __name__ == "__main__":
    main()
