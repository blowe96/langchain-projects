"""
Stage 2: Generate a review report for duplicate groups that exist ENTIRELY within
photos-import (no takeout-extracted involvement) - these need a human judgment call.

This script does NOT move or delete anything - it only produces a sorted report.
"""

import re
from pathlib import Path

REPORT_PATH = Path("/mnt/storage_sata/duplicate_report.txt")
OUTPUT_PATH = Path("/mnt/storage_sata/stage2_review_report.txt")

PHOTOS_IMPORT = "/mnt/storage_sata/photos-import"
TAKEOUT = "/mnt/storage_sata/takeout-extracted"

COPY_PATTERN = re.compile(r"(- ?copy|\(\d+\)\.[a-zA-Z0-9]+$)", re.IGNORECASE)


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


def looks_like_accidental_copy(paths):
    parents = set(str(Path(p).parent) for p in paths)
    if len(parents) != 1:
        return False
    for p in paths:
        if COPY_PATTERN.search(Path(p).name):
            return True
    return False


def main():
    groups = parse_groups(REPORT_PATH)

    same_source_groups = []
    for group in groups:
        in_import = [p for p in group if p.startswith(PHOTOS_IMPORT)]
        in_takeout = [p for p in group if p.startswith(TAKEOUT)]
        if in_import and not in_takeout:
            same_source_groups.append(group)

    print(f"Same-source-only groups (all within photos-import): {len(same_source_groups)}")

    obvious_copies = [g for g in same_source_groups if looks_like_accidental_copy(g)]
    needs_judgment = [g for g in same_source_groups if not looks_like_accidental_copy(g)]

    print(f"  Likely accidental copies (same folder, 'Copy'/'(N)' pattern): {len(obvious_copies)}")
    print(f"  Needs your judgment (different folders / no obvious pattern): {len(needs_judgment)}")

    with open(OUTPUT_PATH, "w") as f:
        f.write(f"STAGE 2 REVIEW REPORT\n")
        f.write(f"Total groups: {len(same_source_groups)}\n")
        f.write(f"  Likely accidental copies: {len(obvious_copies)}\n")
        f.write(f"  Needs your judgment: {len(needs_judgment)}\n")
        f.write("=" * 80 + "\n\n")

        f.write("### SECTION A: LIKELY ACCIDENTAL COPIES (review these first - quick wins) ###\n\n")
        for i, group in enumerate(obvious_copies, 1):
            size_mb = Path(group[0]).stat().st_size / (1024 * 1024) if Path(group[0]).exists() else 0
            f.write(f"Group A{i} - {size_mb:.2f} MB\n")
            for p in group:
                f.write(f"    {p}\n")
            f.write("\n")

        f.write("\n### SECTION B: NEEDS YOUR JUDGMENT (different folders - may be intentional) ###\n\n")
        for i, group in enumerate(needs_judgment, 1):
            size_mb = Path(group[0]).stat().st_size / (1024 * 1024) if Path(group[0]).exists() else 0
            f.write(f"Group B{i} - {size_mb:.2f} MB\n")
            for p in group:
                f.write(f"    {p}\n")
            f.write("\n")

    print(f"\nReport written to: {OUTPUT_PATH}")
    print("Section A (top of file) = quick wins, likely safe to clean up")
    print("Section B (bottom of file) = review carefully, may be intentional")

if __name__ == "__main__":
    main()
