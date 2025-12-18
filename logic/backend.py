from pathlib import Path
from typing import Dict, Any, List
from logic.image_utils import dicom_to_gray_np

import cv2
import joblib
import numpy as np

from model.models import Case
from logic.mongo_db import MongoDB

_db = MongoDB()


def get_initial_cases() -> List[Case]:
    return _db.list_cases()


def run_ai(case: Case) -> Dict[str, Any]:
    db_result = _db.get_ai_result(case.case_id)
    model = joblib.load(str(Path(__file__).resolve().parent.parent / "minimal_AI_model" / "models" / "mlp.joblib"))
    scaler = joblib.load(str(Path(__file__).resolve().parent.parent / "minimal_AI_model" / "models" / "scaler.joblib"))
    class_names = np.load(
        str(Path(__file__).resolve().parent.parent / "minimal_AI_model" / "models" / "class_names.npy"),
        allow_pickle=True
    ).tolist()

    pred_class, probs = predict_ct_section(case.ct_images[0], model, scaler, class_names=class_names)

    return {
        "biomarkers": [
            {"name": "TTF-1", "value": probs[0]},
            {"name": "CK7", "value": probs[1]},
        ],
        "explanation": f"The model predicts the CT section belongs to class {"TTF-1" if probs[0] > probs[1] else "CK7"} with probability {max(probs[0], probs[1])}.",
        "heatmap": db_result.get("heatmap")
    }


def add_case(case: Case) -> str:
    return _db.insert_case(case)


def update_case(case: Case) -> bool:
    return _db.update_case(case)


def delete_case(case_id: str) -> bool:
    return _db.delete_case(case_id)


def predict_ct_section(img_path, model, scaler, img_size=64, class_names=None):
    if img_path.lower().endswith(".dcm"):
        img = dicom_to_gray_np(img_path)
    else:
        img = cv2.imread(img_path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ValueError(f"Could not read image: {img_path}")

    img = cv2.resize(img, (img_size, img_size))
    img = img.astype(np.float32) / 255.0
    x = img.flatten().reshape(1, -1)

    x_scaled = scaler.transform(x)
    probs = model.predict_proba(x_scaled)[0]
    pred_idx = np.argmax(probs)
    pred_class = class_names[pred_idx] if class_names else pred_idx
    return pred_class, probs