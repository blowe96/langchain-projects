"""
Face clustering - Layer 3 of the photo indexing project.
"""

import os
import sqlite3
import numpy as np
from pathlib import Path
from sklearn.cluster import DBSCAN

DB_PATH = Path("/mnt/storage_sata/photo_index.db")

EPS = float(os.environ.get("CLUSTER_EPS", 0.9))
MIN_SAMPLES = int(os.environ.get("CLUSTER_MIN_SAMPLES", 2))


def main():
    conn = sqlite3.connect(DB_PATH)

    print("Loading face embeddings from database...")
    rows = conn.execute("SELECT id, embedding FROM faces").fetchall()
    print(f"Total faces: {len(rows)}")

    if not rows:
        print("No faces found - run face detection first.")
        return

    face_ids = [r[0] for r in rows]
    embeddings = np.stack([
        np.frombuffer(r[1], dtype=np.float32) for r in rows
    ])
    print(f"Embedding matrix shape: {embeddings.shape}")

    print(f"\nRunning DBSCAN (eps={EPS}, min_samples={MIN_SAMPLES})...")
    print("This may take a few minutes for 100k+ faces...")

    db = DBSCAN(
        eps=EPS,
        min_samples=MIN_SAMPLES,
        metric="euclidean",
        algorithm="ball_tree",
        n_jobs=-1,
    )
    labels = db.fit_predict(embeddings)

    unique_labels = set(labels)
    unique_labels.discard(-1)
    n_clusters = len(unique_labels)
    n_noise = int(np.sum(labels == -1))

    print(f"\nClusters found: {n_clusters}")
    print(f"Unclustered (noise) faces: {n_noise}")

    sizes = [int(np.sum(labels == lbl)) for lbl in unique_labels]
    if sizes:
        sizes.sort(reverse=True)
        print(f"Largest clusters (face count): {sizes[:10]}")
        print(f"Smallest clusters (face count): {sizes[-10:]}")

    print("\nWriting clusters to database...")

    conn.execute("DELETE FROM clusters")
    conn.execute("UPDATE faces SET cluster_id = NULL")

    label_to_cluster_id = {}
    for label in unique_labels:
        member_mask = labels == label
        member_embeddings = embeddings[member_mask]
        representative = member_embeddings.mean(axis=0)
        representative = representative / np.linalg.norm(representative)

        cursor = conn.execute(
            "INSERT INTO clusters (representative_embedding, face_count) VALUES (?, ?)",
            (representative.astype(np.float32).tobytes(), int(member_mask.sum())),
        )
        label_to_cluster_id[label] = cursor.lastrowid

    for face_id, label in zip(face_ids, labels):
        if label == -1:
            continue
        conn.execute(
            "UPDATE faces SET cluster_id = ? WHERE id = ?",
            (label_to_cluster_id[label], face_id),
        )

    conn.commit()
    conn.close()

    print("\n" + "=" * 60)
    print("CLUSTERING COMPLETE")
    print("=" * 60)
    print(f"Clusters created: {n_clusters}")
    print(f"Faces left unclustered: {n_noise}")
    print(f"\nIf too many small clusters for the same person, try a higher EPS.")
    print(f"If different people are getting merged, try a lower EPS.")
    print(f"Re-run with: CLUSTER_EPS=<value> uv run cluster_faces.py")


if __name__ == "__main__":
    main()
