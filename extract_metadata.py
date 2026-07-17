"""
Metadata extraction pipeline - Layer 1 of the photo indexing project.

For every photo/video under PHOTOS_ROOT:
  1. Compute a content hash (stable identity, survives file moves/renames)
  2. Skip if already indexed (by hash) - just update the path if it moved
  3. Extract standard metadata:
       - Photos: EXIF (date, GPS, camera) via Pillow/pillow-heif
       - Videos: ffprobe (creation date)
       - Fallback: JSON sidecar (Google Takeout style), then filesystem mtime
  4. Insert/update a row in the `files` table

This does NOT do face detection or AI captioning - those are later layers.
Safe to re-run any time; already-processed files are skipped quickly via hash lookup.
"""

import hashlib
import json
import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path

from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS
import pillow_heif

pillow_heif.register_heif_opener()

PHOTOS_ROOT = Path("/mnt/storage_sata/photos-import")
DB_PATH = Path("/mnt/storage_sata/photo_index.db")

PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic", ".gif", ".webp", ".bmp", ".tiff"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mts", ".3gp"}

CHUNK_SIZE = 1024 * 1024


def compute_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK_SIZE):
            h.update(chunk)
    return h.hexdigest()


def convert_gps(value, ref):
    try:
        degrees, minutes, seconds = value
        decimal = float(degrees) + float(minutes) / 60 + float(seconds) / 3600
        if ref in ("S", "W"):
            decimal = -decimal
        return decimal
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def extract_exif(path: Path):
    date_taken = gps_lat = gps_lon = camera_make = camera_model = None
    try:
        with Image.open(path) as img:
            exif_data = img.getexif()
            if not exif_data:
                return date_taken, gps_lat, gps_lon, camera_make, camera_model

            tags = {TAGS.get(k, k): v for k, v in exif_data.items()}

            raw_date = tags.get("DateTimeOriginal") or tags.get("DateTime")
            if raw_date:
                try:
                    dt = datetime.strptime(raw_date, "%Y:%m:%d %H:%M:%S")
                    date_taken = dt.isoformat()
                except ValueError:
                    pass

            camera_make = tags.get("Make")
            camera_model = tags.get("Model")

            gps_info_tag = exif_data.get_ifd(0x8825) if hasattr(exif_data, "get_ifd") else None
            if gps_info_tag:
                gps_tags = {GPSTAGS.get(k, k): v for k, v in gps_info_tag.items()}
                lat = gps_tags.get("GPSLatitude")
                lat_ref = gps_tags.get("GPSLatitudeRef")
                lon = gps_tags.get("GPSLongitude")
                lon_ref = gps_tags.get("GPSLongitudeRef")
                if lat and lat_ref:
                    gps_lat = convert_gps(lat, lat_ref)
                if lon and lon_ref:
                    gps_lon = convert_gps(lon, lon_ref)
    except Exception:
        pass

    return date_taken, gps_lat, gps_lon, camera_make, camera_model


def extract_json_sidecar(path: Path):
    json_path = path.parent / (path.name + ".json")
    if not json_path.exists():
        return None, None, None
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        ts = data.get("photoTakenTime", {}).get("timestamp")
        date_taken = datetime.fromtimestamp(int(ts)).isoformat() if ts else None

        geo = data.get("geoData", {})
        lat = geo.get("latitude")
        lon = geo.get("longitude")
        if lat == 0.0 and lon == 0.0:
            lat = lon = None
        return date_taken, lat, lon
    except (json.JSONDecodeError, OSError, ValueError):
        return None, None, None


def extract_video_metadata(path: Path):
    date_taken = None
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "quiet", "-print_format", "json",
                "-show_entries", "format_tags=creation_time", str(path)
            ],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            raw_date = data.get("format", {}).get("tags", {}).get("creation_time")
            if raw_date:
                date_taken = raw_date.replace("Z", "+00:00")
                date_taken = datetime.fromisoformat(date_taken).isoformat()
    except (subprocess.TimeoutExpired, json.JSONDecodeError, ValueError, OSError):
        pass
    return date_taken


def get_filesystem_date(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime).isoformat()


def process_file(path: Path, media_type: str):
    content_hash = compute_hash(path)
    file_size = path.stat().st_size

    date_taken = None
    date_source = None
    gps_lat = gps_lon = None
    camera_make = camera_model = None

    if media_type == "photo":
        date_taken, gps_lat, gps_lon, camera_make, camera_model = extract_exif(path)
        if date_taken:
            date_source = "exif"

    elif media_type == "video":
        date_taken = extract_video_metadata(path)
        if date_taken:
            date_source = "ffprobe"

    if not date_taken or gps_lat is None:
        json_date, json_lat, json_lon = extract_json_sidecar(path)
        if not date_taken and json_date:
            date_taken = json_date
            date_source = "json"
        if gps_lat is None and json_lat is not None:
            gps_lat, gps_lon = json_lat, json_lon

    if not date_taken:
        date_taken = get_filesystem_date(path)
        date_source = "filesystem"

    return {
        "file_path": str(path),
        "content_hash": content_hash,
        "media_type": media_type,
        "file_size_bytes": file_size,
        "date_taken": date_taken,
        "date_source": date_source,
        "gps_lat": gps_lat,
        "gps_lon": gps_lon,
        "camera_make": camera_make,
        "camera_model": camera_model,
    }


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")

    existing_paths = {
        row[0] for row in conn.execute("SELECT file_path FROM files").fetchall()
    }
    existing_hashes = {
        row[0] for row in conn.execute("SELECT content_hash FROM files").fetchall()
    }
    print(f"Already indexed: {len(existing_paths)} files")

    print("Scanning for files...")
    all_files = []
    for path in PHOTOS_ROOT.rglob("*"):
        if not path.is_file():
            continue
        ext = path.suffix.lower()
        if ext in PHOTO_EXTENSIONS:
            all_files.append((path, "photo"))
        elif ext in VIDEO_EXTENSIONS:
            all_files.append((path, "video"))

    print(f"Total media files found: {len(all_files)}")

    new_count = 0
    skipped_count = 0
    error_count = 0

    for i, (path, media_type) in enumerate(all_files, 1):
        if i % 500 == 0:
            print(f"  ...processed {i}/{len(all_files)} (new: {new_count}, skipped: {skipped_count}, errors: {error_count})")

        if str(path) in existing_paths:
            skipped_count += 1
            continue

        try:
            content_hash = compute_hash(path)
        except (OSError, PermissionError) as e:
            print(f"  Could not read {path}: {e}")
            error_count += 1
            continue

        if content_hash in existing_hashes:
            conn.execute(
                "UPDATE files SET file_path=?, updated_at=CURRENT_TIMESTAMP WHERE content_hash=?",
                (str(path), content_hash),
            )
            skipped_count += 1
            continue

        try:
            metadata = process_file(path, media_type)
        except Exception as e:
            print(f"  Error processing {path}: {e}")
            error_count += 1
            continue

        conn.execute(
            """
            INSERT INTO files (
                file_path, content_hash, media_type, file_size_bytes,
                date_taken, date_source, gps_lat, gps_lon,
                camera_make, camera_model, metadata_extracted_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(file_path) DO UPDATE SET
                content_hash=excluded.content_hash,
                updated_at=CURRENT_TIMESTAMP
            """,
            (
                metadata["file_path"], metadata["content_hash"], metadata["media_type"],
                metadata["file_size_bytes"], metadata["date_taken"], metadata["date_source"],
                metadata["gps_lat"], metadata["gps_lon"],
                metadata["camera_make"], metadata["camera_model"],
            ),
        )
        existing_hashes.add(content_hash)
        new_count += 1

        if new_count % 200 == 0:
            conn.commit()

    conn.commit()

    print("\n" + "=" * 60)
    print("METADATA EXTRACTION COMPLETE")
    print("=" * 60)
    print(f"New files indexed: {new_count}")
    print(f"Already indexed (skipped): {skipped_count}")
    print(f"Errors: {error_count}")

    conn.close()


if __name__ == "__main__":
    main()
