"""
Sanity check: verify InsightFace initializes correctly and detects the GPU.
This will download InsightFace's model files on first run (a few hundred MB).
"""

import insightface
from insightface.app import FaceAnalysis

print("Initializing InsightFace...")

app = FaceAnalysis(name="buffalo_l", providers=["CUDAExecutionProvider", "CPUExecutionProvider"])
app.prepare(ctx_id=0, det_size=(640, 640))

print("\nInsightFace initialized successfully.")
print("Provider check - if this says CUDA, the GPU is being used:")
print(app.models["detection"].session.get_providers())
