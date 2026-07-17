"""
Find exact duplicate files across two photo/video libraries using content hashing (SHA-256).

Compares:
  - /mnt/storage_sata/photos-import      (manually organized year folders)
  - /mnt/storage_sata/takeout-extracted  (recovered Google Photos Takeout)

This is READ-ONLY. It only reports duplicates - nothing is deleted or moved.

Output: a report file listing groups of duplicate files, with file size and
both paths, so you can review before deciding what (if anything) to remove.
"""

import hashlib
from pathlib import Path
from collections import defaultdict

SOURCES = [
    Path("/mnt/storage_sata/photos-import"),
    Path("/mnt/storage_sata/takeout-extracted"),
]

MEDIA_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".mp4", ".mov", ".heic",
    ".gif", ".webp", ".avi", ".mts", ".3gp", ".bmp", ".tiff"
}

REPORT_PATH = Path("/mnt/storage_sata/duplicate_report.txt")

CHUNK_SIZE = 1024 * 1024  # 1MB chunks for hashing large video files efficiently


def hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK_SIZE):
            h.update(chunk)
    return h.hexdigest()


def main():
    size_groups = defaultdict(list)

    print("Step 1: Scanning files and grouping by size...")
    total_files = 0
    for source in SOURCES:
        if not source.exists():
            print(f"  WARNING: {source} does not exist, skipping.")
            continue
        for path in source.rglob("*"):
            if path.is_file() and path.suffix.lower() in MEDIA_EXTENSIONS:
                total_files += 1
                if total_files % 10000 == 0:
                    print(f"  ...scanned {total_files} files so far")
                size = path.stat().st_size
                size_groups[size].append(path)

    print(f"Total media files scanned: {total_files}")

    candidates = {size: paths for size, paths in size_groups.items() if len(paths) > 1}
    candidate_file_count = sum(len(paths) for paths in candidates.values())
    print(f"Files sharing a size with at least one other file: {candidate_file_count}")
    print("(Files with a unique size are skipped - they can't have a duplicate)\n")

    print("Step 2: Hashing candidate files to confirm true duplicates...")
    hash_groups = defaultdict(list)
    hashed_count = 0
    for size, paths in candidates.items():
        for path in paths:
            try:
                file_hash = hash_file(path)
                hash_groups[file_hash].append(path)
            except (PermissionError, OSError) as e:
                print(f"  Could not read {path}: {e}")
            hashed_count += 1
            if hashed_count % 2000 == 0:
                print(f"  ...hashed {hashed_count}/{candidate_file_count} candidate files")

    duplicate_groups = {h: paths for h, paths in hash_groups.items() if len(paths) > 1}

    total_duplicate_files = sum(len(paths) for paths in duplicate_groups.values())
    total_wasted_bytes = sum(
        paths[0].stat().st_size * (len(paths) - 1) for paths in duplicate_groups.values()
    )
    wasted_gb = total_wasted_bytes / (1024 ** 3)

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Duplicate groups found:            {len(duplicate_groups)}")
    print(f"Total files involved in duplicates: {total_duplicate_files}")
    print(f"Space that could be reclaimed:      {wasted_gb:.2f} GB")
    print(f"(reclaimed = keeping just 1 copy per group)")

    with open(REPORT_PATH, "w") as f:
        f.write(f"Duplicate report - {len(duplicate_groups)} groups, {total_duplicate_files} files, ~{wasted_gb:.2f} GB reclaimable\n")
        f.write("=" * 80 + "\n\n")
        for i, (file_hash, paths) in enumerate(duplicate_groups.items(), 1):
            size_mb = paths[0].stat().st_size / (1024 * 1024)
            f.write(f"Group {i} - {len(paths)} copies, {size_mb:.2f} MB each - hash {file_hash[:12]}...\n")
            for p in paths:
                f.write(f"    {p}\n")
            f.write("\n")

    print(f"\nFull report written to: {REPORT_PATH}")

if __name__ == "__main__":
    main()
