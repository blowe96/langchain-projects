#!/usr/bin/env python3
"""
resolve_duplicate_groups.py

Reads the duplicate-review report produced by resolve_duplicates.py
(/mnt/storage_sata/duplicate_review_needed.txt) and safely resolves the
narrow, verifiable case: exactly 2 files in a group, both exist on disk,
both share the exact same DateTimeOriginal (confirming same photo), and
one has a clearly higher resolution than the other. In that case the
lower-resolution file is the duplicate.

Everything else (3+ files in a group, missing files, mismatched or missing
timestamps, equal/tied resolution) is left for manual review - never
auto-resolved. This matches the same "verify before touching anything"
convention as every other script in this project.

Deleted files are never permanently removed by this script - they are
moved to a dated trash folder so they can be recovered if a mistake is
ever found, mirroring the --backup-dir pattern used in the offsite backup.

Usage:
    python3 resolve_duplicate_groups.py            (dry-run, writes report only)
    python3 resolve_duplicate_groups.py --apply     (moves auto-resolved duplicates to trash)
"""

import subprocess
import sys
import json
import shutil
from pathlib import Path
from datetime import datetime

REVIEW_FILE = Path("/mnt/storage_sata/duplicate_review_needed.txt")
REPORT_FILE = Path("/mnt/storage_sata/duplicate_cleanup_report.txt")
TRASH_ROOT = Path("/mnt/storage_sata/duplicate_cleanup_trash")

# Path prefix used inside the review file (container path) needs mapping
# to the real host path
CONTAINER_PREFIX = "/usr/src/app/external/photos-import/"
HOST_PREFIX = "/mnt/storage_sata/photos-import/"

APPLY = "--apply" in sys.argv


def map_path(container_path: str) -> Path:
    if container_path.startswith(CONTAINER_PREFIX):
        return Path(HOST_PREFIX + container_path[len(CONTAINER_PREFIX):])
    return Path(container_path)


def parse_groups(text: str):
    groups = []
    current_files = None
    for line in text.splitlines():
        if line.startswith("Group "):
            if current_files is not None:
                groups.append(current_files)
            current_files = []
        elif line.strip().startswith("/") and current_files is not None:
            current_files.append(map_path(line.strip()))
    if current_files:
        groups.append(current_files)
    return groups


def get_exif_batch(paths):
    """Run exiftool once for all paths, return dict keyed by resolved path string."""
    if not paths:
        return {}
    str_paths = [str(p) for p in paths]
    result = subprocess.run(
        ["exiftool", "-j", "-ImageWidth", "-ImageHeight", "-DateTimeOriginal"] + str_paths,
        capture_output=True, text=True
    )
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {}
    return {entry.get("SourceFile"): entry for entry in data}


def main():
    if not REVIEW_FILE.exists():
        print(f"ERROR: {REVIEW_FILE} not found.", file=sys.stderr)
        sys.exit(1)

    groups = parse_groups(REVIEW_FILE.read_text())
    print(f"Parsed {len(groups)} groups from {REVIEW_FILE}")

    # Batch exif lookup across every file in every group, once, for speed
    all_paths = [p for group in groups for p in group]
    exif_data = get_exif_batch(all_paths)

    auto_resolve = []   # list of (keep_path, delete_path, reason_details)
    manual_review = []  # list of (group_paths, reason)

    for group in groups:
        if len(group) != 2:
            manual_review.append((group, f"{len(group)} files in group (not a simple pair)"))
            continue

        a, b = group
        missing = [p for p in group if not p.exists()]
        if missing:
            manual_review.append((group, f"file(s) missing on disk: {missing}"))
            continue

        info_a = exif_data.get(str(a))
        info_b = exif_data.get(str(b))
        if not info_a or not info_b:
            manual_review.append((group, "exiftool could not read one or both files"))
            continue

        date_a = info_a.get("DateTimeOriginal")
        date_b = info_b.get("DateTimeOriginal")
        if not date_a or not date_b or date_a != date_b:
            manual_review.append((group, f"capture timestamps differ or missing: '{date_a}' vs '{date_b}'"))
            continue

        res_a = info_a.get("ImageWidth", 0) * info_a.get("ImageHeight", 0)
        res_b = info_b.get("ImageWidth", 0) * info_b.get("ImageHeight", 0)

        if res_a == res_b:
            manual_review.append((group, "identical resolution - cannot determine which is the duplicate"))
            continue

        keep, delete = (a, b) if res_a > res_b else (b, a)
        keep_info = info_a if res_a > res_b else info_b
        delete_info = info_b if res_a > res_b else info_a
        auto_resolve.append((keep, delete, keep_info, delete_info, date_a))

    # Write the report
    lines = []
    lines.append(f"Duplicate Cleanup Report - generated {datetime.now()}")
    lines.append(f"Source: {REVIEW_FILE}")
    lines.append("=" * 80)
    lines.append("")
    lines.append(f"AUTO-RESOLVABLE (matching timestamp, one clearly lower resolution): {len(auto_resolve)}")
    lines.append("-" * 80)
    for keep, delete, keep_info, delete_info, ts in auto_resolve:
        lines.append(f"  Capture time: {ts}")
        lines.append(f"  KEEP:   {keep}  ({keep_info.get('ImageWidth')}x{keep_info.get('ImageHeight')})")
        lines.append(f"  DELETE: {delete}  ({delete_info.get('ImageWidth')}x{delete_info.get('ImageHeight')})")
        lines.append("")

    lines.append("")
    lines.append(f"NEEDS MANUAL REVIEW: {len(manual_review)}")
    lines.append("-" * 80)
    for group, reason in manual_review:
        lines.append(f"  Reason: {reason}")
        for p in group:
            exists_marker = "" if p.exists() else " [MISSING]"
            lines.append(f"    {p}{exists_marker}")
        lines.append("")

    REPORT_FILE.write_text("\n".join(lines))
    print(f"\nReport written to {REPORT_FILE}")
    print(f"  Auto-resolvable: {len(auto_resolve)}")
    print(f"  Needs manual review: {len(manual_review)}")

    if not APPLY:
        print("\n[DRY RUN] No files were moved. Review the report, then re-run with --apply to move the")
        print(f"lower-resolution duplicates listed above into {TRASH_ROOT}/<timestamp>/")
        return

    # Apply: move auto-resolved duplicates to a dated trash folder, preserving
    # their relative path under photos-import so they can be found/restored
    trash_dir = TRASH_ROOT / datetime.now().strftime("%Y%m%d_%H%M%S")
    moved = 0
    for keep, delete, keep_info, delete_info, ts in auto_resolve:
        try:
            rel = delete.relative_to(HOST_PREFIX)
        except ValueError:
            rel = delete.name
        dest = trash_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(delete), str(dest))
        moved += 1

    print(f"\n=== Moved {moved} lower-resolution duplicates to {trash_dir} ===")
    print("Nothing was permanently deleted - review the trash folder and remove it")
    print("manually once you're confident, or leave it as an extra safety margin.")


if __name__ == "__main__":
    main()
