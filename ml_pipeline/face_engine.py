import os
import cv2
import pickle
import numpy as np
from deepface import DeepFace
from sklearn.svm import SVC

MODEL_BACKEND = "ArcFace"

def get_face_embeddings(image_path_or_array):
    try:
        result = DeepFace.represent(
            img_path=image_path_or_array, 
            model_name=MODEL_BACKEND, 
            enforce_detection=False, 
            detector_backend="opencv",
            align=True
        )
        if result and len(result) > 0:
            return result[0]["embedding"]
    except Exception as e:
        print(f"Embedding Error: {e}")
    return None

def train_admin_svm(admin_id, collected_dir):
    admin_folder = os.path.join(collected_dir, f"admin_{admin_id}")
    features_path = os.path.join(admin_folder, "features.pkl")
    model_path = os.path.join(admin_folder, "svm_model.pkl")
    
    if not os.path.exists(features_path):
        if os.path.exists(model_path): os.remove(model_path)
        return False
    
    with open(features_path, 'rb') as f:
        data = pickle.load(f)
    
    X, y = list(data['X']), list(data['y'])
    unique_classes = len(set(y))
    
    # 🟢 Agar 1 hi user hai, toh SVM ki jagah hum direct matching ya bypass karenge
    if len(X) > 0 and unique_classes >= 2:
        model = SVC(kernel='linear', probability=True)
        model.fit(X, y)
        with open(model_path, 'wb') as f:
            pickle.dump(model, f)
        print(f"✅ ArcFace SVM Model trained successfully for Admin {admin_id}!")
        return True
    else:
        if os.path.exists(model_path):
            os.remove(model_path)
        print(f"⚠️ Notice: SVM needs at least 2 different users. Currently {unique_classes} user(s) found.")
        return False

def add_user_embeddings(admin_id, user_name, image_paths, collected_dir):
    admin_folder = os.path.join(collected_dir, f"admin_{admin_id}")
    os.makedirs(admin_folder, exist_ok=True)
    features_path = os.path.join(admin_folder, "features.pkl")
    
    new_X, new_y = [], []
    for path in image_paths:
        img = cv2.imread(path)
        if img is not None:
            embedding = get_face_embeddings(img)
            if embedding:
                new_X.append(embedding)
                new_y.append(user_name)
    
    if not new_X: return False
    
    if os.path.exists(features_path):
        with open(features_path, 'rb') as f:
            data = pickle.load(f)
        X, y = list(data['X']), list(data['y'])
    else:
        X, y = [], []
        
    X.extend(new_X)
    y.extend(new_y)
    
    with open(features_path, 'wb') as f:
        pickle.dump({'X': np.array(X), 'y': np.array(y)}, f)
        
    train_admin_svm(admin_id, collected_dir)
    return True

def remove_user_from_embeddings(admin_id, user_name, collected_dir):
    admin_folder = os.path.join(collected_dir, f"admin_{admin_id}")
    features_path = os.path.join(admin_folder, "features.pkl")
    
    if not os.path.exists(features_path): return
    
    with open(features_path, 'rb') as f:
        data = pickle.load(f)
    
    X, y = list(data['X']), list(data['y'])
    filtered = [(x_item, y_item) for x_item, y_item in zip(X, y) if y_item != user_name]
    
    if filtered:
        new_X = np.array([item[0] for item in filtered])
        new_y = np.array([item[1] for item in filtered])
        with open(features_path, 'wb') as f:
            pickle.dump({'X': new_X, 'y': new_y}, f)
    else:
        if os.path.exists(features_path): os.remove(features_path)
        
    # 🟢 Yahin par train_admin_svm call hona zaroori tha jo chhoot gaya tha!
    train_admin_svm(admin_id, collected_dir)