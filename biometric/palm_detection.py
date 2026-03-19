import base64
import hashlib
import os
import sqlite3
import cv2
import mediapipe as mp
import numpy as np
from flask import Flask, jsonify, request
# from flask_cors import CORS 
from sklearn.metrics.pairwise import cosine_similarity
app = Flask(__name__)
# CORS(app) # Allow React/Vanilla JS to send webcam frames
current_dir = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(current_dir, "biometrics.sqlite3")
MODEL_PATH = os.path.join(current_dir, "hand_landmarker.task")

# Liveness configuration
LIVENESS_REQUIRED = os.environ.get("LIVENESS_REQUIRED", "0") == "1"
LIVENESS_MIN = float(os.environ.get("LIVENESS_MIN", "0.01"))
MIN_LIVENESS_FRAMES = int(os.environ.get("MIN_LIVENESS_FRAMES", "2"))

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_biometrics (
          user_id TEXT PRIMARY KEY,
          embedding BLOB NOT NULL,
          dim INTEGER NOT NULL,
          created_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

init_db()

# Initialize MediaPipe
mp_hands = mp.tasks.vision.HandLandmarker
BaseOptions = mp.tasks.BaseOptions
VisionRunningMode = mp.tasks.vision.RunningMode

options = mp.tasks.vision.HandLandmarkerOptions(
    base_options=BaseOptions(model_asset_path=MODEL_PATH),
    running_mode=VisionRunningMode.IMAGE,
    num_hands=1,
)
detector = mp_hands.create_from_options(options)

def decode_image_bytes_to_bgr(img_bytes):
    arr = np.frombuffer(img_bytes, dtype=np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)

def parse_request_frames():
    """Robustly extracts BGR frames from JSON or Multipart requests."""
    frames = []
    
    # 1. Handle Multipart (Postman File Upload)
    if request.files and "image" in request.files:
        img_bytes = request.files["image"].read()
        bgr = decode_image_bytes_to_bgr(img_bytes)
        if bgr is not None: frames.append(bgr)
        return frames

    # 2. Handle JSON (Base64 from Node.js/Webcam)
    data = request.get_json(silent=True)

    raw_inputs = []

    if data:
        if isinstance(data.get("images_base64"), list):
            raw_inputs.extend(data.get("images_base64"))

        if isinstance(data.get("image_base64"), str):
            raw_inputs.append(data.get("image_base64"))

    for s in raw_inputs:
        if not isinstance(s, str): continue
        # Strip "data:image/jpeg;base64," if present
        if "," in s:
            s = s.split(",")[1]
        try:
            img_bytes = base64.b64decode(s)
            bgr = decode_image_bytes_to_bgr(img_bytes)
            if bgr is not None: frames.append(bgr)
        except:
            continue
    return frames

def extract_features(landmarks):
    pts = np.array([[lm.x, lm.y, lm.z] for lm in landmarks], dtype=np.float32)
    wrist = pts[0]
    pts_centered = pts - wrist
    palm_scale = float(np.linalg.norm(pts[9] - wrist)) + 1e-6
    pts_normalized = pts_centered / palm_scale
    flat = pts_normalized.flatten()
    flat = flat - float(flat.mean())
    flat = flat / (float(np.linalg.norm(flat)) + 1e-6)
    return flat.astype(np.float32).reshape(1, -1)

def save_embedding(user_id, embedding):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO user_biometrics (user_id, embedding, dim, created_at)
        VALUES (?, ?, ?, datetime('now'))
        ON CONFLICT(user_id) DO UPDATE SET embedding=excluded.embedding, created_at=excluded.created_at
    """, (str(user_id), embedding.tobytes(), int(embedding.shape[1])))
    conn.commit()
    conn.close()

def load_embedding(user_id):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT embedding, dim FROM user_biometrics WHERE user_id = ?", (str(user_id),))
    row = cur.fetchone()
    conn.close()
    if not row: return None
    return np.frombuffer(row[0], dtype=np.float32).reshape(1, -1)


@app.route("/enroll", methods=["POST"])
def enroll():
    try:
        data = request.get_json(silent=True) or {}
        user_id = data.get("user_id") or request.form.get("user_id")

        if not user_id:
            return jsonify({"error": "user_id required"}), 400

        frames = parse_request_frames()

        if not frames:
            return jsonify({"error": "No valid image received"}), 400

        if len(frames) != 1:
            return jsonify({
                "error": "Exactly one image required",
                "count": len(frames)
            }), 400

        rgb = cv2.cvtColor(frames[0], cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        result = detector.detect(mp_image)

        if not result.hand_landmarks:
            return jsonify({"error": "No hand detected"}), 400

        features = extract_features(result.hand_landmarks[0])
        save_embedding(user_id, features)

        return jsonify({
            "status": "enrolled",
            "user_id": user_id
        }), 201

    except Exception as e:
        print("Enroll error:", str(e))  # 👈 important debug
        return jsonify({
            "error": "Enrollment failed",
            "message": str(e)
        }), 500
    

@app.route("/verify", methods=["POST"])
def verify():
    try:
        data = request.get_json(silent=True) or {}
        user_id = data.get("user_id")
        stored = load_embedding(user_id)
        if stored is None: return jsonify({"error": "User not enrolled"}), 404

        frames = parse_request_frames()
        if not frames: return jsonify({"error": "No image found"}), 400

        # Feature extraction
        feature_seq = []
        for frame in frames:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            res = detector.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
            if res.hand_landmarks:
                feature_seq.append(extract_features(res.hand_landmarks[0]).flatten())

        if not feature_seq: return jsonify({"error": "Hand not recognized"}), 400

        # Similarity check
        probe = feature_seq[0].reshape(1, -1)
        score = float(cosine_similarity(stored, probe)[0][0])
        
        return jsonify({"biometric_confidence": round(score, 4), "user_id": user_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(port=5001, debug=True)