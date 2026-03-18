from flask import Flask, jsonify
import cv2
import mediapipe as mp
import numpy as np
import hashlib
from sklearn.metrics.pairwise import cosine_similarity

app = Flask(__name__)

mp_hands = mp.tasks.vision.HandLandmarker
BaseOptions = mp.tasks.BaseOptions
VisionRunningMode = mp.tasks.vision.RunningMode

MODEL_PATH = "hand_landmarker.task"

options = mp.tasks.vision.HandLandmarkerOptions(
    base_options=BaseOptions(model_asset_path=MODEL_PATH),
    running_mode=VisionRunningMode.IMAGE,
    num_hands=1
)

detector = mp_hands.create_from_options(options)

stored_features = None

# -------------------------
# Extract features
# -------------------------
def extract_features(landmarks):
    return np.array([[lm.x, lm.y, lm.z] for lm in landmarks]).flatten().reshape(1, -1)

# -------------------------
# Hash
# -------------------------
def hash_features(features):
    return hashlib.sha256(features.tobytes()).hexdigest()

# -------------------------
# Capture from camera
# -------------------------
def capture_frame():
    cap = cv2.VideoCapture(0)
    ret, frame = cap.read()
    cap.release()
    return frame

# -------------------------
# ENROLL
# -------------------------
@app.route("/enroll/<user_id>")
def enroll(user_id):
    global stored_features

    frame = capture_frame()

    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame)
    result = detector.detect(mp_image)

    if not result.hand_landmarks:
        return jsonify({"error": "No hand detected"})

    features = extract_features(result.hand_landmarks[0])
    stored_features = features

    hash_val = hash_features(features)

    return jsonify({
        "status": features.tolist(),
        "hash": hash_val
    })

# -------------------------
# VERIFY
# -------------------------
@app.route("/verify/<user_id>")
def verify(user_id):
    global stored_features

    if stored_features is None:
        return jsonify({"error": "User not enrolled"})

    frame = capture_frame()

    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame)
    result = detector.detect(mp_image)

    if not result.hand_landmarks:
        return jsonify({"error": "No hand detected"})

    new_features = extract_features(result.hand_landmarks[0])

    score = cosine_similarity(stored_features, new_features)[0][0]

    hash_val = hash_features(new_features)

    return jsonify({
        "biometric_confidence": float(score),
        "hash": hash_val
    })

if __name__ == "__main__":
    app.run(port=5001)