"""
Analyze a Google Takeout extraction folder.

Reports:
- Media files with a matching JSON sidecar (recoverable metadata)
- Media files with NO JSON sidecar (media exists, just no extra metadata)
- JSON files with NO matching media (still orphaned / potentially missing)

Excludes account-level and album-level metadata JSONs (not photo sidecars).
Attempts fuzzy/prefix matching for truncated filenames.

Does not modify or move any files - read-only analysis.
"""

import os
from pathlib import Path

ROOT = Path("/mnt/storage_sata/takeout-extracted")

MEDIA_EXTENSIONS = {".jpg", ".jpeg", ".png", ".mp4", ".mov", ".heic", ".gif", ".webp", ".avi"}

# Non-photo JSON files that live at the account or album level - never expected to match media
IGNORE_JSON_NAMES = {
    "metadata.json",
    "print-subscriptions.json",
    "user-generated-memory-titles.json",
    "shared_album_comments.json",
}

def main():
    media_by_dir = {}   # dir -> list of (filename_lower, full_path)
    json_files = {}      # stem_path -> full path (exact match candidates)
    ignored_json_count = 0
    real_json_files = []

    print("Scanning files...")
    total = 0
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        total += 1
        if total % 10000 == 0:
            print(f"  ...scanned {total} files so far")

        if path.suffix.lower() == ".json":
            if path.name in IGNORE_JSON_NAMES:
                ignored_json_count += 1
                continue
            real_json_files.append(path)
            media_name = path.name[:-5]  # strip ".json"
            key = str(path.parent / media_name)
            json_files[key] = path
        elif path.suffix.lower() in MEDIA_EXTENSIONS:
            media_by_dir.setdefault(str(path.parent), []).append((path.name.lower(), path))

    # Build exact-match media lookup too
    media_files = {}
    for dir_path, files in media_by_dir.items():
        for fname_lower, full_path in files:
            media_files[str(full_path)] = full_path

    matched = 0
    media_no_json = []
    json_no_media = []
    fuzzy_matched = 0

    matched_keys = set()
    for key, media_path in media_files.items():
        if key in json_files:
            matched += 1
            matched_keys.add(key)
        else:
            media_no_json.append(media_path)

    for key, json_path in json_files.items():
        if key in matched_keys:
            continue
        expected_name = Path(key).name.lower()
        parent_dir = str(Path(key).parent)
        candidates = media_by_dir.get(parent_dir, [])

        prefix = expected_name[:15]
        found_fuzzy = False
        for fname_lower, full_path in candidates:
            if fname_lower.startswith(prefix) or expected_name.startswith(fname_lower[:15]):
                found_fuzzy = True
                break

        if found_fuzzy:
            fuzzy_matched += 1
        else:
            json_no_media.append(json_path)

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Total files scanned:                  {total}")
    print(f"Total media files found:              {len(media_files)}")
    print(f"Non-photo JSONs ignored (account/album): {ignored_json_count}")
    print(f"Total real photo JSON sidecars:       {len(real_json_files)}")
    print(f"Media files WITH exact JSON match:    {matched}")
    print(f"Media files with NO JSON:             {len(media_no_json)}")
    print(f"JSON matched via fuzzy/truncated name: {fuzzy_matched}")
    print(f"JSON files STILL with NO media match: {len(json_no_media)}")

    if json_no_media:
        out_path = ROOT.parent / "orphaned_json_report.txt"
        with open(out_path, "w") as f:
            for p in json_no_media:
                f.write(str(p) + "\n")
        print(f"\nList of truly orphaned JSON files written to: {out_path}")

    if media_no_json:
        out_path2 = ROOT.parent / "media_without_json_report.txt"
        with open(out_path2, "w") as f:
            for p in media_no_json:
                f.write(str(p) + "\n")
        print(f"List of media without JSON written to: {out_path2}")

if __name__ == "__main__":
    main()
