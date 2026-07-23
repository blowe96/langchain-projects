"""
Vision captioning pipeline - Layer 4 of the photo indexing project.

For every file where tags_processed_at IS NULL:
  - Photos: send the image to Qwen2.5-VL (via Ollama), ask for a caption
    plus structured tags (objects, colors, scene, activity)
  - Videos: extract one representative frame (50% through), caption that
  - Store the caption on `files.caption` and structured tags in `tags`
  - Mark the file as tags_processed_at = now

This is the slowest step in the pipeline (GPU-bound vision model inference
per file), so it respects the overnight processing window - stops gracefully
at END_HOUR rather than being killed mid-file. Safe to re-run any night.
"""

import io
import json
import os
import re
import sqlite3
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

import ollama
from PIL import Image
import pillow_heif

pillow_heif.register_heif_opener()

DB_PATH = Path("/mnt/storage_sata/photo_index.db")
MODEL = "qwen2.5vl:7b"

_end_hour_raw = os.environ.get("INDEXING_END_HOUR", "6")
END_HOUR = None if _end_hour_raw.lower() in ("none", "off", "") else int(_end_hour_raw)
COMMIT_EVERY = 20

PROMPT = """Look at this image and respond with ONLY a JSON object (no other text, no markdown formatting) in this exact format:

{"caption": "one sentence description", "objects": ["object1", "object2"], "colors": {"object1": "color1"}, "scene": "indoor/outdoor scene type", "activity": "what is happening"}

Keep the caption to one sentence. List only clearly visible objects. Only include colors for objects where color is a notable/distinguishing feature (e.g. a yellow car, not a person's shirt unless clearly the focus)."""


def past_cutoff() -> bool:
    if END_HOUR is None:
        return False
    now = datetime.now()
    return now.hour >= END_HOUR and now.hour < 12


def image_to_jpeg_bytes(path: Path) -> bytes:
    with Image.open(path) as img:
        img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=90)
        return buf.getvalue()


def get_video_duration(path: Path):
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_entries", "format=duration", str(path)],
            capture_output=True, text=True, timeout=30
        )
        data = json.loads(result.stdout)
        return float(data["format"]["duration"])
    except Exception:
        return None


def extract_video_frame_bytes(path: Path, timestamp_seconds: float):
    with tempfile.TemporaryDirectory() as tmpdir:
        frame_path = Path(tmpdir) / "frame.jpg"
        try:
            result = subprocess.run(
                [
                    "ffmpeg", "-y", "-ss", str(timestamp_seconds), "-i", str(path),
                    "-frames:v", "1", "-q:v", "2", str(frame_path)
                ],
                capture_output=True, timeout=30
            )
            if result.returncode == 0 and frame_path.exists():
                return frame_path.read_bytes()
        except Exception:
            pass
    return None


def parse_model_response(raw_text: str):
    match = re.search(r"\{.*\}", raw_text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def caption_image(image_bytes: bytes):
    response = ollama.chat(
        model=MODEL,
        messages=[{"role": "user", "content": PROMPT, "images": [image_bytes]}],
        options={"num_ctx": 8192},
    )
    raw_text = response["message"]["content"]
    return parse_model_response(raw_text)


def store_tags(conn, file_id, parsed, frame_timestamp=None):
    caption = parsed.get("caption")
    if caption:
        conn.execute("UPDATE files SET caption = ? WHERE id = ?", (caption, file_id))

    for obj in parsed.get("objects", []):
        if not isinstance(obj, str):
            continue
        conn.execute(
            "INSERT INTO tags (file_id, tag_text, category, frame_timestamp) VALUES (?, ?, ?, ?)",
            (file_id, obj.lower().strip(), "object", frame_timestamp),
        )

    colors = parsed.get("colors", {})
    if isinstance(colors, dict):
        for obj, color in colors.items():
            if isinstance(color, str):
                conn.execute(
                    "INSERT INTO tags (file_id, tag_text, category, frame_timestamp) VALUES (?, ?, ?, ?)",
                    (file_id, color.lower().strip(), "color", frame_timestamp),
                )

    scene = parsed.get("scene")
    if isinstance(scene, str) and scene.strip():
        conn.execute(
            "INSERT INTO tags (file_id, tag_text, category, frame_timestamp) VALUES (?, ?, ?, ?)",
            (file_id, scene.lower().strip(), "scene", frame_timestamp),
        )

    activity = parsed.get("activity")
    if isinstance(activity, str) and activity.strip():
        conn.execute(
            "INSERT INTO tags (file_id, tag_text, category, frame_timestamp) VALUES (?, ?, ?, ?)",
            (file_id, activity.lower().strip(), "activity", frame_timestamp),
        )


def process_photo(conn, file_id, path: Path):
    image_bytes = image_to_jpeg_bytes(path)
    parsed = caption_image(image_bytes)
    if parsed:
        store_tags(conn, file_id, parsed)
        return True
    return False


def process_video(conn, file_id, path: Path):
    duration = get_video_duration(path)
    if not duration:
        return False

    frame_bytes = extract_video_frame_bytes(path, duration * 0.5)
    if not frame_bytes:
        return False

    parsed = caption_image(frame_bytes)
    if parsed:
        store_tags(conn, file_id, parsed, frame_timestamp=duration * 0.5)
        return True
    return False


def main():
    print(f"Using vision model: {MODEL}")
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")

    rows = conn.execute(
        "SELECT id, file_path, media_type FROM files WHERE tags_processed_at IS NULL AND is_missing = 0"
    ).fetchall()
    total = len(rows)
    print(f"Files needing captioning: {total}")

    processed = 0
    successes = 0
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
                ok = process_photo(conn, file_id, path)
            else:
                ok = process_video(conn, file_id, path)

            if ok:
                successes += 1
            conn.execute("UPDATE files SET tags_processed_at = CURRENT_TIMESTAMP WHERE id = ?", (file_id,))
            processed += 1

        except Exception as e:
            print(f"  Error processing {file_path}: {e}")
            errors += 1

        if processed % COMMIT_EVERY == 0:
            conn.commit()
            print(f"  ...processed {processed}/{total} (captioned: {successes}, errors: {errors})")

    conn.commit()

    print("\n" + "=" * 60)
    print("VISION CAPTIONING RUN COMPLETE (or paused at window cutoff)")
    print("=" * 60)
    print(f"Files processed this run: {processed}")
    print(f"Successfully captioned: {successes}")
    print(f"Errors: {errors}")
    remaining = total - processed
    print(f"Remaining files still needing captioning: {remaining}")

    conn.close()


if __name__ == "__main__":
    main()
