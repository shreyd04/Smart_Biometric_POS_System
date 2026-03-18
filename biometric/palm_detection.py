import base64
import hashlib
import os
import sqlite3

import cv2
import mediapipe as mp
import numpy as np
from flask import Flask, jsonify, request
from sklearn.metrics.pairwise import cosine_similarity

app = Flask(__name__)

DB_PATH = os.environ.get("BIOMETRIC_DB_PATH", "biometrics.sqlite3")
MODEL_PATH = os.environ.get("HAND_LANDMARKER_MODEL_PATH", "hand_landmarker.task")

LIVENESS_REQUIRED = os.environ.get("LIVENESS_REQUIRED", "0") == "1"
LIVENESS_MIN = float(os.environ.get("LIVENESS_MIN", "0.01"))
MIN_LIVENESS_FRAMES = int(os.environ.get("MIN_LIVENESS_FRAMES", "2"))


def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS user_biometrics (
          user_id TEXT PRIMARY KEY,
          embedding BLOB NOT NULL,
          dim INTEGER NOT NULL,
          created_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()


init_db()

mp_hands = mp.tasks.vision.HandLandmarker
BaseOptions = mp.tasks.BaseOptions
VisionRunningMode = mp.tasks.vision.RunningMode

options = mp.tasks.vision.HandLandmarkerOptions(
    base_options=BaseOptions(model_asset_path=MODEL_PATH),
    running_mode=VisionRunningMode.IMAGE,
    num_hands=1,
)

detector = mp_hands.create_from_options(options)


def extract_features(landmarks):
    """
    Scale/translation normalized embedding:
    - Translate to wrist origin (0)
    - Scale by wrist->middle_mcp distance (9)
    - Global mean-center and L2-normalize flattened vector
    """
    pts = np.array([[lm.x, lm.y, lm.z] for lm in landmarks], dtype=np.float32)
    wrist = pts[0]
    pts_centered = pts - wrist

    middle_mcp = pts[9]
    palm_scale = float(np.linalg.norm(middle_mcp - wrist)) + 1e-6
    pts_normalized = pts_centered / palm_scale

    flat = pts_normalized.flatten()
    flat = flat - float(flat.mean())
    flat = flat / (float(np.linalg.norm(flat)) + 1e-6)
    return flat.astype(np.float32).reshape(1, -1)


def hash_features(features):
    return hashlib.sha256(features.tobytes()).hexdigest()


def save_embedding(user_id, embedding):
    emb = embedding.astype(np.float32).reshape(1, -1)
    dim = int(emb.shape[1])
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO user_biometrics (user_id, embedding, dim, created_at)
        VALUES (?, ?, ?, datetime('now'))
        ON CONFLICT(user_id) DO UPDATE SET
          embedding=excluded.embedding,
          dim=excluded.dim,
          created_at=excluded.created_at
        """
        ,
        (str(user_id), emb.tobytes(), dim),
    )
    conn.commit()
    conn.close()


def load_embedding(user_id):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT embedding, dim FROM user_biometrics WHERE user_id = ?", (str(user_id),))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    blob, dim = row
    vec = np.frombuffer(blob, dtype=np.float32)
    if vec.size != int(dim):
        return None
    return vec.reshape(1, -1)


def decode_image_bytes_to_bgr(img_bytes):
    arr = np.frombuffer(img_bytes, dtype=np.uint8)
    bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    return bgr


def parse_request_frames():
    """
    Supports:
      - multipart/form-data with file field 'image' (single frame)
      - JSON with 'image_base64' (single frame)
      - JSON with 'images_base64' (list of frames for liveness)
    Returns: list of BGR frames (np arrays)
    """
    frames = []

    if request.files and "image" in request.files:
        f = request.files["image"]
        img_bytes = f.read()
        bgr = decode_image_bytes_to_bgr(img_bytes)
        if bgr is not None:
            frames.append(bgr)
        return frames

    data = request.get_json(silent=True) or {}
    images_b64 = data.get("images_base64")
    if isinstance(images_b64, list) and images_b64:
        for s in images_b64:
            if not isinstance(s, str):
                continue
            try:
                img_bytes = base64.b64decode(s, validate=True)
            except Exception:
                continue
            bgr = decode_image_bytes_to_bgr(img_bytes)
            if bgr is not None:
                frames.append(bgr)
        return frames

    image_b64 = data.get("image_base64")
    if isinstance(image_b64, str) and image_b64:
        try:
            img_bytes = base64.b64decode(image_b64, validate=True)
        except Exception:
            return []
        bgr = decode_image_bytes_to_bgr(img_bytes)
        if bgr is not None:
            frames.append(bgr)
    return frames


def bgr_to_srgb(frame_bgr):
    rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    return mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)


def compute_liveness_score(feature_seq):
    if len(feature_seq) < 2:
        return 0.0
    sims = []
    for i in range(len(feature_seq) - 1):
        a = feature_seq[i].reshape(1, -1)
        b = feature_seq[i + 1].reshape(1, -1)
        sims.append(float(cosine_similarity(a, b)[0][0]))
    avg_sim = float(np.mean(sims))
    return max(0.0, 1.0 - avg_sim)


@app.route("/enroll", methods=["POST"])
def enroll():
    try:
        data = request.get_json(silent=True) or {}
        user_id = data.get("user_id") or request.form.get("user_id")
        if not user_id:
            return jsonify({"error": "user_id required"}), 400

        frames = parse_request_frames()
        if len(frames) != 1:
            return jsonify({"error": "Exactly one image required for enroll"}), 400

        mp_image = bgr_to_srgb(frames[0])
        result = detector.detect(mp_image)
        if not result.hand_landmarks:
            return jsonify({"error": "No hand detected"}), 400

        features = extract_features(result.hand_landmarks[0])
        save_embedding(user_id, features)

        return jsonify({"status": "enrolled", "hash": hash_features(features)}), 201

    except Exception as e:
        return jsonify({"error": "Enrollment failed", "message": str(e)}), 500


@app.route("/verify", methods=["POST"])
def verify():
    try:
        data = request.get_json(silent=True) or {}
        user_id = data.get("user_id") or request.form.get("user_id")
        if not user_id:
            return jsonify({"error": "user_id required"}), 400

        stored = load_embedding(user_id)
        if stored is None:
            return jsonify({"error": "User not enrolled"}), 404

        frames = parse_request_frames()
        if not frames:
            return jsonify({"error": "Invalid or missing image"}), 400

        if LIVENESS_REQUIRED and len(frames) < MIN_LIVENESS_FRAMES:
            return jsonify({
                "error": "Liveness frames required",
                "min_frames": MIN_LIVENESS_FRAMES
            }), 400

        feature_seq = []
        for frame in frames:
            mp_image = bgr_to_srgb(frame)
            result = detector.detect(mp_image)
            if not result.hand_landmarks:
                continue
            feature_seq.append(extract_features(result.hand_landmarks[0]).flatten())

        if not feature_seq:
            return jsonify({"error": "No hand detected"}), 400

        liveness_score = None
        if len(feature_seq) >= 2:
            liveness_score = compute_liveness_score(feature_seq)
            if LIVENESS_REQUIRED and liveness_score < LIVENESS_MIN:
                return jsonify({
                    "error": "Liveness check failed",
                    "liveness_score": liveness_score
                }), 401

        probe = feature_seq[0].reshape(1, -1)
        score = float(cosine_similarity(stored, probe)[0][0])

        return jsonify({
            "biometric_confidence": score,
            "hash": hash_features(probe),
            "liveness_score": liveness_score
        })

    except Exception as e:
        return jsonify({"error": "Verification failed", "message": str(e)}), 500


@app.route("/enroll/<user_id>", methods=["GET", "POST"])
def enroll_legacy(user_id):
    return jsonify({
        "error": "Legacy endpoint disabled. Use POST /enroll with image_base64 or multipart image."
    }), 400


@app.route("/verify/<user_id>", methods=["GET", "POST"])
def verify_legacy(user_id):
    return jsonify({
        "error": "Legacy endpoint disabled. Use POST /verify with image_base64 or images_base64."
    }), 400


if __name__ == "__main__":
    app.run(port=5001)