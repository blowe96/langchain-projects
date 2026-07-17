"""
Stage 1: Quarantine (not delete) takeout-extracted files that are exact duplicates
of something already in photos-import.

Rule applied:
  - For each duplicate group, if at least one copy exists in photos-import,
    move ALL takeout-extracted copies in that group to a quarantine folder,
    preserving their relative path (so they can be restored later if needed).
  - Files inside photos-import are NEVER touched, no matter how many copies
    of them exist or where they are.

This is a MOVE, not a delete - nothing is permanently removed. A manifest
(CSV-like text file) is written recording every original path and its new
quarantine path, so this can be undone if needed.
"""

import shutil
from pathlib import Path

REPORT_PATH = Path("/mnt/storage_sata/duplicate_report.txt")
QUARANTINE_DIR = Path("/mnt/storage_sata/quarantine_takeout_duplicates")
MANIFEST_PATH = Path("/mnt/storage_sata/quarantine_manifest.txt")

PHOTOS_IMPORT = "/mnt/storage_sata/photos-import"
TAKEOUT = "/mnt/storage_sata/takeout-extracted"


def parse_groups(report_path):
    groups = []
    current_group = []
    with open(report_path) as f:
        for line in f:
            line = line.rstrip("\n")
            if line.startswith("Group "):
                if current_group:
                    groups.append(current_group)
                current_group = []
            elif line.startswith("    /mnt/"):
                current_group.append(line.strip())
    if current_group:
        groups.append(current_group)
    return groups


def main():
    groups = parse_groups(REPORT_PATH)
    print(f"Total duplicate groups: {len(groups)}")

    QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)

    moved_count = 0
    skipped_no_import_copy = 0
    total_bytes_moved = 0

    with open(MANIFEST_PATH, "w") as manifest:
        manifest.write("original_path\tquarantine_path\n")

        for group in groups:
            in_import = [p for p in group if p.startswith(PHOTOS_IMPORT)]
            in_takeout = [p for p in group if p.startswith(TAKEOUT)]

            if not in_import or not in_takeout:
                skipped_no_import_copy += 1
                continue

            for takeout_path_str in in_takeout:
                src = Path(takeout_path_str)
                if not src.exists():
                    continue

                rel_path = src.relative_to(TAKEOUT)
                dest = QUARANTINE_DIR / rel_path
                dest.parent.mkdir(parents=True, exist_ok=True)

                try:
                    size = src.stat().st_size
                    shutil.move(str(src), str(dest))
                    manifest.write(f"{src}\t{dest}\n")
                    moved_count += 1
                    total_bytes_moved += size
                    if moved_count % 1000 == 0:
                        print(f"  ...quarantined {moved_count} files so far")
                except (OSError, shutil.Error) as e:
                    print(f"  Could not move {src}: {e}")

    moved_gb = total_bytes_moved / (1024 ** 3)

    print("\n" + "=" * 60)
    print("STAGE 1 COMPLETE")
    print("=" * 60)
    print(f"Files quarantined (moved, not deleted): {moved_count}")
    print(f"Space freed from photos-import/takeout:  {moved_gb:.2f} GB")
    print(f"Same-source-only groups skipped (Stage 2 territory): {skipped_no_import_copy}")
    print(f"\nQuarantined files are in: {QUARANTINE_DIR}")
    print(f"Manifest (for restore if needed): {MANIFEST_PATH}")

if __name__ == "__main__":
    main()
