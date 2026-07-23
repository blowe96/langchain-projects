"""
Backend API for the photo indexing project's web app.
"""

import io
import sqlite3
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from PIL import Image
import pillow_heif

pillow_heif.register_heif_opener()

DB_PATH = Path("/mnt/storage_sata/photo_index.db")

app = FastAPI(title="Photo Index API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@app.get("/")
def serve_frontend():
    return FileResponse(Path(__file__).parent / "index.html")


@app.get("/api/clusters")
def list_clusters(min_faces: int = 2, labeled: bool | None = None, limit: int = 100, offset: int = 0):
    conn = get_conn()
    query = "SELECT id, person_name, face_count FROM clusters WHERE face_count >= ?"
    params = [min_faces]
    if labeled is True:
        query += " AND person_name IS NOT NULL"
    elif labeled is False:
        query += " AND person_name IS NULL"
    query += " ORDER BY face_count DESC LIMIT ? OFFSET ?"
    params += [limit, offset]

    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/api/clusters/{cluster_id}/faces")
def cluster_faces(cluster_id: int, limit: int = 9):
    conn = get_conn()
    rows = conn.execute(
        "SELECT id FROM faces WHERE cluster_id = ? LIMIT ?", (cluster_id, limit)
    ).fetchall()
    conn.close()
    return [r["id"] for r in rows]


class LabelRequest(BaseModel):
    person_name: str


@app.post("/api/clusters/{cluster_id}/label")
def label_cluster(cluster_id: int, body: LabelRequest):
    conn = get_conn()
    conn.execute(
        "UPDATE clusters SET person_name = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (body.person_name.strip(), cluster_id),
    )
    conn.commit()
    conn.close()
    return {"status": "ok"}


class MergeRequest(BaseModel):
    source_cluster_id: int
    target_cluster_id: int


@app.post("/api/clusters/merge")
def merge_clusters(body: MergeRequest):
    conn = get_conn()
    conn.execute(
        "UPDATE faces SET cluster_id = ? WHERE cluster_id = ?",
        (body.target_cluster_id, body.source_cluster_id),
    )
    conn.execute(
        """UPDATE clusters SET face_count = (
             SELECT COUNT(*) FROM faces WHERE cluster_id = ?
           ) WHERE id = ?""",
        (body.target_cluster_id, body.target_cluster_id),
    )
    conn.execute("DELETE FROM clusters WHERE id = ?", (body.source_cluster_id,))
    conn.commit()
    conn.close()
    return {"status": "ok"}


@app.get("/api/face_thumbnail/{face_id}")
def face_thumbnail(face_id: int):
    conn = get_conn()
    row = conn.execute(
        """
        SELECT f.file_path, fa.bbox_x, fa.bbox_y, fa.bbox_width, fa.bbox_height
        FROM faces fa JOIN files f ON fa.file_id = f.id
        WHERE fa.id = ?
        """,
        (face_id,),
    ).fetchone()
    conn.close()

    if not row:
        raise HTTPException(404, "Face not found")

    path = Path(row["file_path"])
    if not path.exists():
        raise HTTPException(404, "Source file missing")

    try:
        with Image.open(path) as img:
            img = img.convert("RGB")
            x, y, w, h = row["bbox_x"], row["bbox_y"], row["bbox_width"], row["bbox_height"]
            pad_x, pad_y = w * 0.3, h * 0.3
            left = max(0, x - pad_x)
            top = max(0, y - pad_y)
            right = min(img.width, x + w + pad_x)
            bottom = min(img.height, y + h + pad_y)
            crop = img.crop((left, top, right, bottom))
            crop.thumbnail((200, 200))

            buf = io.BytesIO()
            crop.save(buf, format="JPEG", quality=85)
            buf.seek(0)
            return StreamingResponse(buf, media_type="image/jpeg")
    except Exception as e:
        raise HTTPException(500, f"Could not generate thumbnail: {e}")


@app.get("/api/gallery")
def gallery(
    year: int | None = None,
    person_cluster_id: int | None = None,
    tag: str | None = None,
    media_type: str | None = None,
    limit: int = 60,
    offset: int = 0,
):
    conn = get_conn()

    query = "SELECT DISTINCT f.id, f.file_path, f.media_type, f.date_taken, f.caption FROM files f"
    joins = []
    conditions = ["f.is_missing = 0"]
    params = []

    if person_cluster_id is not None:
        joins.append("JOIN faces fc ON fc.file_id = f.id")
        conditions.append("fc.cluster_id = ?")
        params.append(person_cluster_id)

    if tag:
        joins.append("JOIN tags t ON t.file_id = f.id")
        conditions.append("t.tag_text LIKE ?")
        params.append(f"%{tag.lower()}%")

    if year is not None:
        conditions.append("f.date_taken LIKE ?")
        params.append(f"{year}-%")

    if media_type:
        conditions.append("f.media_type = ?")
        params.append(media_type)

    if joins:
        query += " " + " ".join(joins)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY f.date_taken DESC LIMIT ? OFFSET ?"
    params += [limit, offset]

    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/api/media/{file_id}")
def get_media(file_id: int):
    conn = get_conn()
    row = conn.execute("SELECT file_path FROM files WHERE id = ?", (file_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "File not found")
    path = Path(row["file_path"])
    if not path.exists():
        raise HTTPException(404, "File missing from disk")
    return FileResponse(path)


@app.get("/api/media/{file_id}/thumbnail")
def get_thumbnail(file_id: int, size: int = 300):
    conn = get_conn()
    row = conn.execute("SELECT file_path, media_type FROM files WHERE id = ?", (file_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "File not found")

    path = Path(row["file_path"])
    if not path.exists():
        raise HTTPException(404, "File missing from disk")

    if row["media_type"] != "photo":
        raise HTTPException(400, "Thumbnails only supported for photos currently")

    try:
        with Image.open(path) as img:
            img = img.convert("RGB")
            img.thumbnail((size, size))
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85)
            buf.seek(0)
            return StreamingResponse(buf, media_type="image/jpeg")
    except Exception as e:
        raise HTTPException(500, f"Could not generate thumbnail: {e}")


@app.get("/api/stats")
def stats():
    conn = get_conn()
    total_files = conn.execute("SELECT COUNT(*) c FROM files").fetchone()["c"]
    captioned = conn.execute("SELECT COUNT(*) c FROM files WHERE tags_processed_at IS NOT NULL").fetchone()["c"]
    total_clusters = conn.execute("SELECT COUNT(*) c FROM clusters").fetchone()["c"]
    labeled_clusters = conn.execute("SELECT COUNT(*) c FROM clusters WHERE person_name IS NOT NULL").fetchone()["c"]
    conn.close()
    return {
        "total_files": total_files,
        "captioned_files": captioned,
        "total_clusters": total_clusters,
        "labeled_clusters": labeled_clusters,
    }
