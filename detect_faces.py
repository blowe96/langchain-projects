"""
Face detection pipeline - Layer 2 of the photo indexing project.
"""

import os
import sqlite3
import subprocess
import tempfile
import warnings
from datetime import datetime
from pathlib import Path

warnings.filterwarnings("ignore", category=FutureWarning)

import cv2
import numpy as np
from PIL import Image
import pillow_heif
from insightface.app import FaceAnalysis

pillow_heif.register_heif_opener()

DB_PATH = Path("/mnt/storage_sata/photo_index.db")
END_HOUR = int(os.environ.get("INDEXING_END_HOUR", 6))
VIDEO_FRAME_FRACTIONS = [0.1, 0.5, 0.9]
COMMIT_EVERY = 50


def past_cutoff() -> bool:
    if END_HOUR is None:
        return False
    now = datetime.now()
    return now.hour >= END_HOUR and now.hour < 12


def load_image_bgr(path: Path):
    if path.suffix.lower() == ".heic":
        with Image.open(path) as img:
            img = img.convert("RGB")
            rgb = np.array(img)
            return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    else:
        img = cv2.imread(str(path))
        return img


def get_video_duration(path: Path):
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_entries", "format=duration", str(path)],
            capture_output=True, text=True, timeout=30
        )
        import json
        data = json.loads(result.stdout)
        return float(data["format"]["duration"])
    except Exception:
        return None


def extract_video_frame(path: Path, timestamp_seconds: float, out_path: Path) -> bool:
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-y", "-ss", str(timestamp_seconds), "-i", str(path),
                "-frames:v", "1", "-q:v", "2", str(out_path)
            ],
            capture_output=True, timeout=30
        )
        return result.returncode == 0 and out_path.exists()
    except Exception:
        return False


def process_photo(app, conn, file_id, path: Path):
    img = load_image_bgr(path)
    if img is None:
        return 0

    faces = app.get(img)
    for face in faces:
        embedding = face.normed_embedding.astype(np.float32).tobytes()
        bbox = face.bbox
        conn.execute(
            """
            INSERT INTO faces (file_id, embedding, bbox_x, bbox_y, bbox_width, bbox_height, frame_timestamp)
            VALUES (?, ?, ?, ?, ?, ?, NULL)
            """,
            (file_id, embedding, float(bbox[0]), float(bbox[1]),
             float(bbox[2] - bbox[0]), float(bbox[3] - bbox[1])),
        )
    return len(faces)


def process_video(app, conn, file_id, path: Path):
    duration = get_video_duration(path)
    if not duration:
        return 0

    total_faces = 0
    with tempfile.TemporaryDirectory() as tmpdir:
        for frac in VIDEO_FRAME_FRACTIONS:
            ts = duration * frac
            frame_path = Path(tmpdir) / f"frame_{frac}.jpg"
            if not extract_video_frame(path, ts, frame_path):
                continue

            img = cv2.imread(str(frame_path))
            if img is None:
                continue

            faces = app.get(img)
            for face in faces:
                embedding = face.normed_embedding.astype(np.float32).tobytes()
                bbox = face.bbox
                conn.execute(
                    """
                    INSERT INTO faces (file_id, embedding, bbox_x, bbox_y, bbox_width, bbox_height, frame_timestamp)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (file_id, embedding, float(bbox[0]), float(bbox[1]),
                     float(bbox[2] - bbox[0]), float(bbox[3] - bbox[1]), ts),
                )
            total_faces += len(faces)

    return total_faces


def main():
    print("Initializing InsightFace...")
    app = FaceAnalysis(name="buffalo_l", providers=["CUDAExecutionProvider", "CPUExecutionProvider"])
    app.prepare(ctx_id=0, det_size=(640, 640))
    print("InsightFace ready.\n")

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")

    rows = conn.execute(
        "SELECT id, file_path, media_type FROM files WHERE faces_processed_at IS NULL AND is_missing = 0"
    ).fetchall()
    total = len(rows)
    print(f"Files needing face detection: {total}")

    processed = 0
    total_faces_found = 0
    errors = 0

    for file_id, file_path, media_type in rows:
        if past_cutoff():
            print(f"\nReached end-of-window cutoff ({END_HOUR}:00). Stopping gracefully.")
            break

        path = Path(file_path)
        if not path.exists():
            conn.execute("UPDATE files SET is_missing = 1 WHERE id = ?", (file_id,))
            processed += 1
            continue

        try:
            if media_type == "photo":
                face_count = process_photo(app, conn, file_id, path)
            else:
                face_count = process_video(app, conn, file_id, path)

            conn.execute(
                "UPDATE files SET faces_processed_at = CURRENT_TIMESTAMP WHERE id = ?", (file_id,)
            )
            total_faces_found += face_count
            processed += 1

        except Exception as e:
            print(f"  Error processing {file_path}: {e}")
            errors += 1

        if processed % COMMIT_EVERY == 0:
            conn.commit()
            print(f"  ...processed {processed}/{total} (faces found: {total_faces_found}, errors: {errors})")

    conn.commit()

    print("\n" + "=" * 60)
    print("FACE DETECTION RUN COMPLETE (or paused at window cutoff)")
    print("=" * 60)
    print(f"Files processed this run: {processed}")
    print(f"Total faces found: {total_faces_found}")
    print(f"Errors: {errors}")
    remaining = total - processed
    print(f"Remaining files still needing face detection: {remaining}")

    conn.close()


if __name__ == "__main__":
    main()
