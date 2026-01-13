"""logic/backend.py

Backend functions used by the Tkinter UI.

This module glues together:
  - MongoDB persistence (cases)
  - AI pipeline (DICOM -> NIfTI -> lung mask -> radiomics -> TF model)

It is written to work with *Python 3.12 + TensorFlow 2.16+* where
`model.predict()` may return numpy arrays, lists, or dictionaries (named outputs).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from model.models import Case
from logic.mongo_db import MongoDB


# -------------------- configuration --------------------

TARGET_SHAPE_2D: Tuple[int, int] = (128, 128)
TARGET_SPACING: Tuple[float, float, float] = (1.0, 1.0, 3.8)

CLIP_MIN_HU = -1000.0
CLIP_MAX_HU = 400.0

# Positive thresholds used in your reference script
TTF1_THRESHOLD = 0.60
CK7_THRESHOLD = 0.69


# -------------------- MongoDB --------------------

_db = MongoDB()


# -------------------- AI Pipeline --------------------

class LungCancerPipeline:
    """Full pipeline matching the reference script you provided."""

    def __init__(self, model_path: Path, scaler_path: Path):
        # Lazy imports (keeps UI boot snappier and avoids import-time crashes)
        import tensorflow as tf
        import joblib
        from radiomics import featureextractor

        self.tf = tf
        self.joblib = joblib

        print(f"[INIT] Loading model from: {model_path}")
        self.model = tf.keras.models.load_model(str(model_path))
        print("[INIT] Model loaded.")

        print(f"[INIT] Loading scaler from: {scaler_path}")
        self.scaler = joblib.load(str(scaler_path))
        print("[INIT] Scaler loaded.")

        self.extractor = featureextractor.RadiomicsFeatureExtractor()
        logging.getLogger("radiomics").setLevel(logging.ERROR)
        print("[INIT] Radiomics extractor ready.")

    # ---- DICOM -> NIfTI ----
    def convert_dicom_to_nifti(self, dicom_folder: Path, output_path: Path) -> Path:
        import SimpleITK as sitk

        dicom_folder = Path(dicom_folder)
        if not dicom_folder.is_dir():
            raise ValueError(f"DICOM folder does not exist: {dicom_folder}")

        # Robustly handle multiple series in the same folder by choosing the largest series.
        reader = sitk.ImageSeriesReader()
        series_ids = reader.GetGDCMSeriesIDs(str(dicom_folder)) or []
        if series_ids:
            best_files: List[str] = []
            for sid in series_ids:
                files = reader.GetGDCMSeriesFileNames(str(dicom_folder), sid)
                if len(files) > len(best_files):
                    best_files = files
            dicom_names = best_files
        else:
            dicom_names = reader.GetGDCMSeriesFileNames(str(dicom_folder))

        if not dicom_names:
            raise ValueError(f"No DICOM files found in: {dicom_folder}")

        reader.SetFileNames(dicom_names)
        image = reader.Execute()
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        sitk.WriteImage(image, str(output_path))
        return output_path

    # ---- lung mask ----
    def generate_lung_mask(self, nifti_path: Path, output_mask_path: Path) -> Path:
        import SimpleITK as sitk
        from lungmask import mask as lungmask_model

        input_image = sitk.ReadImage(str(nifti_path))
        segmentation_np = lungmask_model.apply(input_image)
        segmentation_bin = (segmentation_np > 0).astype(np.uint8)
        mask_image = sitk.GetImageFromArray(segmentation_bin)
        mask_image.CopyInformation(input_image)
        output_mask_path = Path(output_mask_path)
        output_mask_path.parent.mkdir(parents=True, exist_ok=True)
        sitk.WriteImage(mask_image, str(output_mask_path), useCompression=True)
        return output_mask_path

    # ---- preprocessing ----
    def _apply_mask_and_normalize(self, ct_img, mask_img):
        import SimpleITK as sitk

        masker = sitk.MaskImageFilter()
        masker.SetOutsideValue(CLIP_MIN_HU)
        masked_ct = masker.Execute(ct_img, mask_img)

        arr = sitk.GetArrayFromImage(masked_ct)
        arr = np.clip(arr, CLIP_MIN_HU, CLIP_MAX_HU)
        arr = (arr - CLIP_MIN_HU) / (CLIP_MAX_HU - CLIP_MIN_HU)

        norm_img = sitk.GetImageFromArray(arr.astype(np.float32))
        norm_img.CopyInformation(ct_img)
        return norm_img

    def preprocess_images(self, ct_path: Path, mask_path: Path, output_dir: Path) -> Tuple[str, str]:
        import SimpleITK as sitk

        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        ct_img = sitk.ReadImage(str(ct_path))
        mask_img = sitk.ReadImage(str(mask_path))
        ct_img = sitk.Cast(ct_img, sitk.sitkFloat32)
        mask_img = sitk.Cast(mask_img, sitk.sitkUInt8)

        old_spacing = ct_img.GetSpacing()
        old_size = ct_img.GetSize()
        new_size = [
            int(round(old_size[0] * (old_spacing[0] / TARGET_SPACING[0]))),
            int(round(old_size[1] * (old_spacing[1] / TARGET_SPACING[1]))),
            int(round(old_size[2] * (old_spacing[2] / TARGET_SPACING[2]))),
        ]

        resampler = sitk.ResampleImageFilter()
        resampler.SetOutputSpacing(TARGET_SPACING)
        resampler.SetSize(new_size)
        resampler.SetOutputOrigin(ct_img.GetOrigin())
        resampler.SetOutputDirection(ct_img.GetDirection())

        resampler.SetInterpolator(sitk.sitkLinear)
        resampler.SetDefaultPixelValue(CLIP_MIN_HU)
        ct_resampled = resampler.Execute(ct_img)

        resampler.SetInterpolator(sitk.sitkNearestNeighbor)
        resampler.SetDefaultPixelValue(0)
        mask_resampled = resampler.Execute(mask_img)

        ct_normalized = self._apply_mask_and_normalize(ct_resampled, mask_resampled)

        ct_out = str(output_dir / "ct_normalized.nii.gz")
        mask_out = str(output_dir / "mask_resampled.nii.gz")
        sitk.WriteImage(ct_normalized, ct_out)
        sitk.WriteImage(mask_resampled, mask_out)

        return ct_out, mask_out

    # ---- radiomics ----
    def extract_radiomics(self, ct_path: str, mask_path: str) -> np.ndarray:
        result = self.extractor.execute(ct_path, mask_path)
        feature_values = [float(v) for k, v in result.items() if str(k).startswith("original_")]
        if not feature_values:
            raise RuntimeError("Radiomics extractor returned no 'original_' features.")
        return np.asarray(feature_values, dtype=np.float32).reshape(1, -1)

    # ---- model prediction ----
    @staticmethod
    def _as_float_array(x: Any) -> np.ndarray:
        """Convert model outputs to a 1D float array."""
        if x is None:
            return np.asarray([], dtype=np.float32)
        if isinstance(x, dict):
            # Some Keras configs might nest outputs. Take first value.
            if x:
                x = next(iter(x.values()))
            else:
                return np.asarray([], dtype=np.float32)
        arr = np.asarray(x, dtype=np.float32)
        return np.squeeze(arr)

    @staticmethod
    def _split_outputs(preds: Any) -> Tuple[np.ndarray, np.ndarray]:
        """Handle ndarray/list/dict outputs from model.predict."""
        # 1) dict of named outputs
        if isinstance(preds, dict):
            keys = list(preds.keys())
            # common names
            ttf = None
            ck7 = None
            for k in keys:
                lk = str(k).lower()
                if ttf is None and ("ttf" in lk or "ttf1" in lk):
                    ttf = preds[k]
                if ck7 is None and ("ck7" in lk or "ck_7" in lk):
                    ck7 = preds[k]

            # fallback: take first two outputs
            if ttf is None or ck7 is None:
                vals = list(preds.values())
                if ttf is None and len(vals) >= 1:
                    ttf = vals[0]
                if ck7 is None and len(vals) >= 2:
                    ck7 = vals[1]

            return LungCancerPipeline._as_float_array(ttf), LungCancerPipeline._as_float_array(ck7)

        # 2) list/tuple of outputs
        if isinstance(preds, (list, tuple)):
            if len(preds) >= 2:
                return LungCancerPipeline._as_float_array(preds[0]), LungCancerPipeline._as_float_array(preds[1])
            if len(preds) == 1:
                a = LungCancerPipeline._as_float_array(preds[0])
                return a, np.zeros_like(a)

        # 3) numpy array (single tensor)
        arr = np.asarray(preds)
        if arr.ndim == 2 and arr.shape[1] >= 2:
            return LungCancerPipeline._as_float_array(arr[:, 0]), LungCancerPipeline._as_float_array(arr[:, 1])
        if arr.ndim == 2 and arr.shape[1] == 1:
            a = LungCancerPipeline._as_float_array(arr[:, 0])
            return a, np.zeros_like(a)
        a = LungCancerPipeline._as_float_array(arr)
        return a, np.zeros_like(a)

    def predict(self, ct_path: str, radiomics_features: np.ndarray) -> Dict[str, Any]:
        import nibabel as nib

        # Scale radiomics
        try:
            radio_scaled = self.scaler.transform(radiomics_features)
        except Exception as e:
            exp = getattr(self.scaler, "n_features_in_", None)
            got = int(radiomics_features.shape[1]) if hasattr(radiomics_features, "shape") else None
            raise RuntimeError(f"Radiomics scaler mismatch (expected={exp}, got={got}): {e}")

        # Load 3D NIfTI volume
        img = nib.load(ct_path)
        vol_3d = img.get_fdata().astype(np.float32)
        if vol_3d.ndim == 3:
            vol_3d = np.expand_dims(vol_3d, axis=-1)

        # Build 2D slices (skip empty slices)
        slices: List[np.ndarray] = []
        depth = vol_3d.shape[2]
        for z in range(depth):
            sl = vol_3d[:, :, z, :]
            sl_resized = self.tf.image.resize(sl, TARGET_SHAPE_2D).numpy()
            if float(np.sum(sl_resized)) > 5.0:
                slices.append(sl_resized)

        if not slices:
            raise RuntimeError("No valid slices found after preprocessing.")

        slices_array = np.asarray(slices, dtype=np.float32)
        radio_array = np.repeat(radio_scaled, len(slices), axis=0)

        preds = self.model.predict([slices_array, radio_array], verbose=0)
        ttf1_vals, ck7_vals = self._split_outputs(preds)

        if ttf1_vals.size == 0:
            raise RuntimeError(f"Model output for TTF1 is empty / invalid: type={type(preds)}")

        ttf1_score = float(np.mean(ttf1_vals))
        ck7_score = float(np.mean(ck7_vals)) if ck7_vals.size else 0.0

        return {
            "Raw_TTF1": ttf1_score,
            "Raw_CK7": ck7_score,
            "TTF1_Class": "POZITIVE" if ttf1_score > TTF1_THRESHOLD else "Negative",
            "CK7_Class": "POZITIVE" if ck7_score > CK7_THRESHOLD else "Negative",
        }


# Keep a single pipeline instance in memory (fast repeated runs)
_PIPELINE: Optional[LungCancerPipeline] = None


def _get_pipeline() -> LungCancerPipeline:
    global _PIPELINE
    if _PIPELINE is not None:
        return _PIPELINE

    base_dir = Path(__file__).resolve().parent.parent
    model_path = base_dir / "ai_model" / "model" / "model_2d_efficientnet_v3_FIXED_LR.keras"
    scaler_path = base_dir / "ai_model" / "model" / "radiomics_scaler.joblib"
    _PIPELINE = LungCancerPipeline(model_path, scaler_path)
    return _PIPELINE


def _resolve_dicom_folder(case: Case) -> Path:
    """Return a DICOM folder path from a Case.

    Works if the Case stores:
      - a folder path in ct_images (single element that is a directory)
      - a list of file paths (returns parent folder of the first file)
    """

    if hasattr(case, "ct_folder"):
        p = Path(getattr(case, "ct_folder"))
        if p.exists():
            return p

    # If it's a list of files, the parent folder is the series folder.
    return Path(case.ct_series_dir)


# -------------------- Public backend API (used by UI) --------------------

def get_initial_cases() -> List[Case]:
    return _db.list_cases()


def add_case(case: Case) -> str:
    return _db.insert_case(case)


def update_case(case: Case) -> bool:
    return _db.update_case(case)


def delete_case(case_id: str) -> bool:
    return _db.delete_case(case_id)


def run_ai(
    case: Case,
    progress_cb: Optional[Callable[[str, str, Optional[float]], None]] = None,
) -> Dict[str, Any]:
    """Run full AI pipeline for a case and return UI-ready results.

    progress_cb(stage, msg, pct):
        - stage: short label for the current step
        - msg: log line (optional)
        - pct: 0..100 for determinate progress, or None for indeterminate steps
    """

    def _emit(stage: str, msg: str = "", pct: Optional[float] = None) -> None:
        if progress_cb is None:
            return
        try:
            progress_cb(stage, msg, pct)
        except Exception:
            # never break pipeline due to UI callback issues
            pass

    pipeline = _get_pipeline()

    dicom_folder = case.ct_series_dir
    if not dicom_folder or not os.path.isdir(dicom_folder):
        raise FileNotFoundError(f"CT DICOM folder not found: {dicom_folder}")

    tmp_dir = os.path.abspath(f"temp_ai_{case.case_id}")
    os.makedirs(tmp_dir, exist_ok=True)

    try:
        _emit("Start", f"Case {case.case_id} · {case.patient_name}", 0)

        nifti_path = os.path.join(tmp_dir, "scan.nii.gz")
        _emit("DICOM → NIfTI", f"Converting DICOM in: {dicom_folder}", 10)
        pipeline.convert_dicom_to_nifti(dicom_folder, nifti_path)
        _emit("DICOM → NIfTI", f"Saved NIfTI: {nifti_path}", 25)

        mask_path = os.path.join(tmp_dir, "mask.nii.gz")
        _emit("Lung segmentation", "Running lungmask segmentation (CPU)...", None)
        pipeline.generate_lung_mask(nifti_path, mask_path)
        _emit("Lung segmentation", f"Saved mask: {mask_path}", 55)

        _emit("Preprocess", "Preprocessing CT + mask...", 65)
        prep_ct, prep_mask = pipeline.preprocess_images(nifti_path, mask_path, tmp_dir)
        _emit("Preprocess", "Preprocessing done.", 75)

        _emit("Radiomics", "Extracting radiomics features...", 80)
        feats = pipeline.extract_radiomics(prep_ct, prep_mask)
        if feats is None:
            raise RuntimeError("Radiomics extraction failed.")
        _emit("Radiomics", f"Radiomics features: {len(feats)}", 86)

        _emit("Predict", "Running model inference...", 92)
        result = pipeline.predict(prep_ct, feats)
        _emit("Predict", "Prediction done.", 98)

        _emit("Done", "AI pipeline complete.", 100)
        return result

    except Exception as e:
        _emit("Error", str(e), 0)
        raise RuntimeError(f"AI pipeline failed for case {case.case_id}: {e}")
