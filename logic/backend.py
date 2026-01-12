from pathlib import Path
from typing import Dict, Any, List
from logic.image_utils import dicom_to_gray_np
from model.models import Case
from logic.mongo_db import MongoDB

import os
import joblib
import numpy as np
import SimpleITK as sitk
import nibabel as nib
import tensorflow as tf
import logging
from lungmask import mask as lungmask_model
from radiomics import featureextractor

_db = MongoDB()

# === CONSTANTE ===
TARGET_SHAPE_2D = (128, 128)
TARGET_SPACING = (1.0, 1.0, 3.8)
CLIP_MIN_HU = -1000.0
CLIP_MAX_HU = 400.0

# === PIPELINE PRINCIPAL ===
class LungCancerPipeline:
    def __init__(self, model_path, scaler_path):
        print(f"[INIT] Loading model from {model_path}")
        try:
            self.model = tf.keras.models.load_model(model_path)
            print("[INIT] Model loaded successfully.")
        except Exception as e:
            print(f"[ERROR] Failed to load model: {e}")
            self.model = None

        print(f"[INIT] Loading scaler from {scaler_path}")
        try:
            self.scaler = joblib.load(scaler_path)
            print("[INIT] Scaler loaded successfully.")
        except Exception as e:
            print(f"[ERROR] Failed to load scaler: {e}")
            self.scaler = None

        self.extractor = featureextractor.RadiomicsFeatureExtractor()
        logging.getLogger("radiomics").setLevel(logging.ERROR)

    def convert_dicom_to_nifti(self, dicom_folder, output_path):
        reader = sitk.ImageSeriesReader()
        dicom_names = reader.GetGDCMSeriesFileNames(str(dicom_folder))
        if not dicom_names:
            raise ValueError(f"No DICOM files in {dicom_folder}")
        reader.SetFileNames(dicom_names)
        image = reader.Execute()
        sitk.WriteImage(image, str(output_path))
        return output_path

    def generate_lung_mask(self, nifti_path, output_mask_path):
        input_image = sitk.ReadImage(str(nifti_path))
        segmentation_np = lungmask_model.apply(input_image)
        segmentation_bin = (segmentation_np > 0).astype(np.uint8)
        mask_image = sitk.GetImageFromArray(segmentation_bin)
        mask_image.CopyInformation(input_image)
        sitk.WriteImage(mask_image, str(output_mask_path), useCompression=True)
        return output_mask_path

    def _apply_mask_and_normalize(self, ct_img, mask_img):
        masker = sitk.MaskImageFilter()
        masker.SetOutsideValue(CLIP_MIN_HU)
        masked_ct = masker.Execute(ct_img, mask_img)
        arr = sitk.GetArrayFromImage(masked_ct)
        arr = np.clip(arr, CLIP_MIN_HU, CLIP_MAX_HU)
        arr = (arr - CLIP_MIN_HU) / (CLIP_MAX_HU - CLIP_MIN_HU)
        norm_img = sitk.GetImageFromArray(arr.astype(np.float32))
        norm_img.CopyInformation(ct_img)
        return norm_img

    def preprocess_images(self, ct_path, mask_path, output_dir):
        ct_img = sitk.ReadImage(str(ct_path))
        mask_img = sitk.ReadImage(str(mask_path))
        ct_img = sitk.Cast(ct_img, sitk.sitkFloat32)
        mask_img = sitk.Cast(mask_img, sitk.sitkUInt8)
        resampler = sitk.ResampleImageFilter()
        resampler.SetOutputSpacing(TARGET_SPACING)
        resampler.SetInterpolator(sitk.sitkLinear)
        resampler.SetDefaultPixelValue(CLIP_MIN_HU)
        new_size = [
            int(round(ct_img.GetSize()[i] * (ct_img.GetSpacing()[i] / TARGET_SPACING[i])))
            for i in range(3)
        ]
        resampler.SetSize(new_size)
        resampler.SetOutputOrigin(ct_img.GetOrigin())
        resampler.SetOutputDirection(ct_img.GetDirection())
        ct_resampled = resampler.Execute(ct_img)
        resampler.SetInterpolator(sitk.sitkNearestNeighbor)
        resampler.SetDefaultPixelValue(0)
        mask_resampled = resampler.Execute(mask_img)
        ct_normalized = self._apply_mask_and_normalize(ct_resampled, mask_resampled)
        ct_out = os.path.join(output_dir, "ct_normalized.nii.gz")
        mask_out = os.path.join(output_dir, "mask_resampled.nii.gz")
        sitk.WriteImage(ct_normalized, ct_out)
        sitk.WriteImage(mask_resampled, mask_out)
        return ct_out, mask_out

    def extract_radiomics(self, ct_path, mask_path):
        result = self.extractor.execute(str(ct_path), str(mask_path))
        feature_values = [float(v) for k, v in result.items() if k.startswith("original_")]
        return np.array(feature_values).reshape(1, -1)

    def predict(self, ct_path, radiomics_features):
        radio_scaled = self.scaler.transform(radiomics_features)
        img = nib.load(ct_path)
        vol_3d = img.get_fdata().astype(np.float32)
        vol_3d = np.expand_dims(vol_3d, -1) if len(vol_3d.shape) == 3 else vol_3d
        slices = [
            tf.image.resize(vol_3d[:, :, z, :], TARGET_SHAPE_2D).numpy()
            for z in range(vol_3d.shape[2])
            if np.sum(vol_3d[:, :, z, :]) > 5.0
        ]
        if not slices:
            return None
        slices_array = np.array(slices)
        radio_array = np.repeat(radio_scaled, len(slices), axis=0)
        preds = self.model.predict([slices_array, radio_array], verbose=0)
        if isinstance(preds, list):
            ttf1_vals, ck7_vals = preds[0], preds[1]
        else:
            ttf1_vals, ck7_vals = preds[:, 0], preds[:, 1]
        ttf1_score = float(np.mean(ttf1_vals))
        ck7_score = float(np.mean(ck7_vals))
        return {
            "Raw_TTF1": ttf1_score,
            "Raw_CK7": ck7_score,
            "TTF1_Class": "POSITIVE" if ttf1_score > 0.60 else "Negative",
            "CK7_Class": "POSITIVE" if ck7_score > 0.69 else "Negative",
        }


# === INTERFAȚĂ BACKEND ===

def get_initial_cases() -> List[Case]:
    return _db.list_cases()


def run_ai(case: Case) -> Dict[str, Any]:
    """
    Rulează întreg pipeline-ul AI (DICOM -> Mask -> Radiomics -> Predict)
    folosind modelul 2D EfficientNet + radiomics scaler.
    """
    base_dir = Path(__file__).resolve().parent
    model_path = base_dir / "ai_model" / "model" / "model_2d_efficientnet_v3_FIXED_LR.keras"
    scaler_path = base_dir / "ai_model" / "model" / "radiomics_scaler.joblib"
    temp_dir = base_dir / "ai_model" / "temp"
    temp_dir.mkdir(exist_ok=True)

    pipeline = LungCancerPipeline(model_path, scaler_path)

    # 1️⃣ Convert DICOM to NIfTI
    nifti_path = temp_dir / "patient_ct.nii.gz"
    pipeline.convert_dicom_to_nifti(Path(case.ct_folder), nifti_path)

    # 2️⃣ Generate Mask
    mask_path = temp_dir / "patient_mask.nii.gz"
    pipeline.generate_lung_mask(nifti_path, mask_path)

    # 3️⃣ Preprocess
    prep_ct, prep_mask = pipeline.preprocess_images(nifti_path, mask_path, temp_dir)

    # 4️⃣ Radiomics + Prediction
    feats = pipeline.extract_radiomics(prep_ct, prep_mask)
    result = pipeline.predict(prep_ct, feats)

    return {
        "biomarkers": [
            {"name": "TTF-1", "value": result["Raw_TTF1"]},
            {"name": "CK7", "value": result["Raw_CK7"]},
        ],
        "explanation": (
            f"Modelul prezice TTF-1: {result['TTF1_Class']} "
            f"(score={result['Raw_TTF1']:.3f}), "
            f"CK7: {result['CK7_Class']} (score={result['Raw_CK7']:.3f})."
        ),
        "heatmap": None,
    }


def add_case(case: Case) -> str:
    return _db.insert_case(case)


def update_case(case: Case) -> bool:
    return _db.update_case(case)


def delete_case(case_id: str) -> bool:
    return _db.delete_case(case_id)
