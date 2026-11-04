"""Face recognition engine: ArcFace embeddings + SVM, with a distance check.

Why the distance check?  An SVM is a *closed-set* classifier: it always picks one of
the enrolled people, so a stranger can still get a high probability.  We therefore
also require the face to be close (cosine distance) to the enrolled samples of the
predicted person.  With only ONE enrolled person no SVM is possible, so the distance
check alone does the matching (the old code treated everybody as unknown in that case).
"""
import os
import pickle
import threading
import cv2
import numpy as np
from deepface import DeepFace
from sklearn.svm import SVC

MODEL_BACKEND = "ArcFace"
COSINE_THRESHOLD = 0.68      # ArcFace cosine threshold used by DeepFace; lower = stricter
SVM_MIN_PROBA = 0.60         # minimum SVM probability for the predicted person

_lock = threading.Lock()
_cache = {}                  # admin_id -> dict(mtime, X, y, svm)


def _normalize(v):
    v = np.asarray(v, dtype=np.float32)
    n = np.linalg.norm(v, axis=-1, keepdims=True)
    return v / np.maximum(n, 1e-9)


def _paths(admin_id, collected_dir):
    folder = os.path.join(collected_dir, f"admin_{admin_id}")
    return folder, os.path.join(folder, "features.pkl"), os.path.join(folder, "svm_model.pkl")


def get_face_embeddings(image_path_or_array):
    """Return the ArcFace embedding (list of floats) for the biggest face, or None."""
    try:
        result = DeepFace.represent(
            img_path=image_path_or_array,
            model_name=MODEL_BACKEND,
            enforce_detection=False,
            detector_backend="opencv",
            align=True,
        )
        if result:
            return result[0]["embedding"]
    except Exception as e:
        print(f"Embedding error: {e}")
    return None


def _load_bundle(admin_id, collected_dir):
    """Load (and cache by file modification time) features + SVM for an admin."""
    _, features_path, model_path = _paths(admin_id, collected_dir)
    if not os.path.exists(features_path):
        return None
    mtime = (os.path.getmtime(features_path),
             os.path.getmtime(model_path) if os.path.exists(model_path) else 0)
    with _lock:
        cached = _cache.get(admin_id)
        if cached and cached["mtime"] == mtime:
            return cached
        with open(features_path, "rb") as f:
            data = pickle.load(f)
        svm = None
        if os.path.exists(model_path):
            with open(model_path, "rb") as f:
                svm = pickle.load(f)
        bundle = {"mtime": mtime, "X": _normalize(data["X"]), "y": np.array(data["y"]), "svm": svm}
        _cache[admin_id] = bundle
        return bundle


def identify(admin_id, embedding, collected_dir):
    """Return (name or None, confidence 0..1) for an embedding."""
    bundle = _load_bundle(admin_id, collected_dir)
    if bundle is None or embedding is None:
        return None, 0.0

    emb = _normalize(embedding)
    dists = 1.0 - bundle["X"] @ emb            # cosine distance to every enrolled sample
    names = bundle["y"]

    if bundle["svm"] is not None and len(set(names)) >= 2:
        probs = bundle["svm"].predict_proba([emb])[0]
        idx = int(np.argmax(probs))
        candidate, proba = str(bundle["svm"].classes_[idx]), float(probs[idx])
        if proba < SVM_MIN_PROBA:
            return None, 0.0
    else:
        candidate = str(names[int(np.argmin(dists))])
        proba = 1.0

    mine = dists[names == candidate]
    best = float(mine.min()) if mine.size else 1.0
    if best > COSINE_THRESHOLD:
        return None, 0.0
    closeness = 1.0 - best / COSINE_THRESHOLD
    return candidate, round(min(1.0, 0.5 * proba + 0.5 * closeness), 2)


def count_samples(admin_id, collected_dir):
    """How many embeddings are stored per person: {name: count}."""
    _, features_path, _ = _paths(admin_id, collected_dir)
    if not os.path.exists(features_path):
        return {}
    with open(features_path, "rb") as f:
        data = pickle.load(f)
    names, counts = np.unique(np.array(data["y"]), return_counts=True)
    return {str(n): int(c) for n, c in zip(names, counts)}


def train_admin_svm(admin_id, collected_dir):
    folder, features_path, model_path = _paths(admin_id, collected_dir)
    if not os.path.exists(features_path):
        if os.path.exists(model_path):
            os.remove(model_path)
        return False
    with open(features_path, "rb") as f:
        data = pickle.load(f)
    X, y = _normalize(data["X"]), list(data["y"])

    if len(X) > 0 and len(set(y)) >= 2:
        model = SVC(kernel="linear", probability=True)
        model.fit(X, y)
        with open(model_path, "wb") as f:
            pickle.dump(model, f)
        print(f"SVM trained for admin {admin_id} ({len(set(y))} people, {len(y)} samples)")
        return True

    if os.path.exists(model_path):
        os.remove(model_path)
    print("Only one person enrolled: using distance matching (SVM needs 2+ people).")
    return False


def _read_features(features_path):
    if os.path.exists(features_path):
        with open(features_path, "rb") as f:
            data = pickle.load(f)
        return list(data["X"]), list(data["y"])
    return [], []


def add_user_embeddings(admin_id, user_name, image_paths, collected_dir):
    folder, features_path, _ = _paths(admin_id, collected_dir)
    os.makedirs(folder, exist_ok=True)

    new_X = []
    for path in image_paths:
        img = cv2.imread(path)
        if img is None:
            continue
        emb = get_face_embeddings(img)
        if emb:
            new_X.append(_normalize(emb))
    if not new_X:
        return False

    X, y = _read_features(features_path)
    keep = [(x, n) for x, n in zip(X, y) if n != user_name]      # re-enrolling replaces old samples
    X = [k[0] for k in keep] + new_X
    y = [k[1] for k in keep] + [user_name] * len(new_X)

    with open(features_path, "wb") as f:
        pickle.dump({"X": np.array(X), "y": np.array(y)}, f)
    train_admin_svm(admin_id, collected_dir)
    return True


def remove_user_from_embeddings(admin_id, user_name, collected_dir):
    _, features_path, _ = _paths(admin_id, collected_dir)
    if not os.path.exists(features_path):
        return
    X, y = _read_features(features_path)
    kept = [(x, n) for x, n in zip(X, y) if n != user_name]
    if kept:
        with open(features_path, "wb") as f:
            pickle.dump({"X": np.array([k[0] for k in kept]), "y": np.array([k[1] for k in kept])}, f)
    else:
        os.remove(features_path)
    train_admin_svm(admin_id, collected_dir)
