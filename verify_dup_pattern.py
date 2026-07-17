"""
Verify duplicate group patterns before deciding on a keep/remove strategy.

Checks:
- How many groups have exactly 2 files (1 from each source) vs 3+ files
- How many groups have both files from the SAME source (no cross-source pair)
- Confirms whether the simple "keep photos-import, quarantine takeout-extracted"
  rule is safe to apply universally
"""

from pathlib import Path
from collections import defaultdict

REPORT_PATH = Path("/mnt/storage_sata/duplicate_report.txt")

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
    print(f"Total groups parsed: {len(groups)}")

    two_file_groups = 0
    multi_file_groups = 0
    clean_cross_source_pairs = 0
    same_source_only_groups = []
    complex_groups = []

    for group in groups:
        if len(group) == 2:
            two_file_groups += 1
            in_import = [p for p in group if p.startswith(PHOTOS_IMPORT)]
            in_takeout = [p for p in group if p.startswith(TAKEOUT)]
            if len(in_import) == 1 and len(in_takeout) == 1:
                clean_cross_source_pairs += 1
            else:
                same_source_only_groups.append(group)
        else:
            multi_file_groups += 1
            complex_groups.append(group)

    print(f"\nGroups with exactly 2 files:           {two_file_groups}")
    print(f"  - Clean 1 import + 1 takeout pairs:  {clean_cross_source_pairs}")
    print(f"  - Both files from SAME source:       {len(same_source_only_groups)}")
    print(f"Groups with 3+ files (complex):         {multi_file_groups}")

    if same_source_only_groups:
        print("\nSample of same-source duplicate groups (first 5):")
        for g in same_source_only_groups[:5]:
            print("  Group:")
            for p in g:
                print(f"    {p}")

    if complex_groups:
        print("\nSample of complex (3+) groups (first 5):")
        for g in complex_groups[:5]:
            print("  Group:")
            for p in g:
                print(f"    {p}")

if __name__ == "__main__":
    main()
