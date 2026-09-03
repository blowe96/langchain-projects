"""
For the final 28 mobile-upload files that didn't match by filename,
check by CONTENT (SHA-256) against the entire archive instead - since
several share a generic filename (lp_image.MOV) that can't be reliably
matched by name alone.
"""

import hashlib
import subprocess
from pathlib import Path
from collections import defaultdict

PHOTOS_IMPORT = Path("/mnt/storage_sata/photos-import")
IMMICH_LIBRARY = Path("/mnt/storage_sata/immich-app/library")


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def run_psql(query: str) -> str:
    result = subprocess.run(
        ["docker", "exec", "-i", "immich_postgres", "psql", "-U", "postgres", "-d", "immich",
         "-t", "-A", "-F", "\t"],
        input=query, capture_output=True, text=True
    )
    return result.stdout


def main():
    query = """
        SELECT "originalFileName", "originalPath"
        FROM asset
        WHERE "originalPath" LIKE '/data/%' AND status = 'active';
    """
    raw = run_psql(query)
    rows = [tuple(l.split("\t")) for l in raw.strip().split("\n") if l.strip()]

    print(f"Checking {len(rows)} files by content against the whole archive...")
    print("Building size index of archive (this may take a minute)...")
    size_index = defaultdict(list)
    for f in PHOTOS_IMPORT.rglob("*"):
        if f.is_file():
            size_index[f.stat().st_size].append(f)
    print(f"Archive indexed: {sum(len(v) for v in size_index.values())} files")

    for filename, container_path in rows:
        rel = container_path[len("/data/"):]
        mobile_path = IMMICH_LIBRARY / rel
        if not mobile_path.exists():
            print(f"  {filename}: mobile file not found on disk")
            continue

        size = mobile_path.stat().st_size
        candidates = size_index.get(size, [])
        mobile_hash = sha256_of(mobile_path) if candidates else None

        match = None
        for c in candidates:
            if sha256_of(c) == mobile_hash:
                match = c
                break

        if match:
            print(f"  MATCH: {filename} -> {match}")
        else:
            print(f"  NO MATCH: {filename} ({size} bytes) - genuinely new content")


if __name__ == "__main__":
    main()
