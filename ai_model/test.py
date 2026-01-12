import os
import tensorflow as tf
import joblib
import numpy as np
import SimpleITK as sitk
import nibabel as nib
import logging
from lungmask import mask as lungmask_model
from radiomics import featureextractor

TARGET_SHAPE_2D = (128, 128)
TARGET_SPACING = (1.0, 1.0, 3.8)
CLIP_MIN_HU = -1000.0
CLIP_MAX_HU = 400.0

class LungCancerPipeline:
    def __init__(self, model_path, scaler_path, use_gpu=True):
        self.use_gpu = use_gpu
        print(f"[INIT] Loading model from: {model_path}")
        try:
            self.model = tf.keras.models.load_model(model_path)
            print("[INIT] Model loaded successfully.")
        except Exception as e:
            print(f"[ERROR] Could not load model: {e}")
            self.model = None

        print(f"[INIT] Loading scaler from: {scaler_path}")
        try:
            self.scaler = joblib.load(scaler_path)
            print("[INIT] Scaler loaded successfully.")
        except Exception as e:
            print(f"[ERROR] Could not load scaler: {e}")
            self.scaler = None

        self.extractor = featureextractor.RadiomicsFeatureExtractor()
        logging.getLogger('radiomics').setLevel(logging.ERROR)

    def convert_dicom_to_nifti(self, dicom_folder, output_path):
        print(f"[1/5] DICOM -> NIfTI...")
        reader = sitk.ImageSeriesReader()
        dicom_names = reader.GetGDCMSeriesFileNames(str(dicom_folder))
        
        if not dicom_names:
            raise ValueError(f"Directory {dicom_folder} does not contain DICOM files.")
            
        reader.SetFileNames(dicom_names)
        image = reader.Execute()
        sitk.WriteImage(image, str(output_path))
        return output_path

    def _standardize_mask(self, mask_img):
        bin_img = sitk.BinaryThreshold(mask_img, lowerThreshold=0.5, upperThreshold=1e9, insideValue=1, outsideValue=0)
        arr = sitk.GetArrayFromImage(bin_img)
        if arr.mean() > 0.5:
            bin_img = sitk.BinaryNot(bin_img)
        
        bin_img = sitk.Cast(bin_img, sitk.sitkUInt8)
        bin_img.CopyInformation(mask_img)
        return bin_img

    def generate_lung_mask(self, nifti_path, output_mask_path):
        print(f"[2/5] Generating lung mask...")
        input_image = sitk.ReadImage(str(nifti_path))
        
        segmentation_np = lungmask_model.apply(input_image) 
        segmentation_bin = (segmentation_np > 0).astype(np.uint8)
        
        mask_image = sitk.GetImageFromArray(segmentation_bin)
        mask_image.CopyInformation(input_image)
        mask_image = self._standardize_mask(mask_image)
        
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
        print(f"[3/5] Preprocessing (Resampling + Normalization)...")
        ct_img = sitk.ReadImage(str(ct_path))
        mask_img = sitk.ReadImage(str(mask_path))
        
        ct_img = sitk.Cast(ct_img, sitk.sitkFloat32)
        mask_img = sitk.Cast(mask_img, sitk.sitkUInt8)

        old_spacing = ct_img.GetSpacing()
        old_size = ct_img.GetSize()
        new_size = [
            int(round(old_size[0] * (old_spacing[0] / TARGET_SPACING[0]))),
            int(round(old_size[1] * (old_spacing[1] / TARGET_SPACING[1]))),
            int(round(old_size[2] * (old_spacing[2] / TARGET_SPACING[2])))
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
        
        ct_out = os.path.join(output_dir, "temp_ct_normalized.nii.gz")
        mask_out = os.path.join(output_dir, "temp_mask_resampled.nii.gz")
        
        sitk.WriteImage(ct_normalized, ct_out)
        sitk.WriteImage(mask_resampled, mask_out)
        
        return ct_out, mask_out

    def extract_radiomics(self, ct_path, mask_path):
        print(f"[4/5] Extracting Radiomics features...")
        try:
            result = self.extractor.execute(str(ct_path), str(mask_path))
            
            feature_values = []
            count = 0
            
            for key, value in result.items():
                if key.startswith("original_"):
                    feature_values.append(float(value))
                    count += 1
            
            if count == 0:
                print("[WARN] Could not find feature 'original_'.")
                return None
                
            print(f" Extracted {count} features.")
            return np.array(feature_values).reshape(1, -1)
            
        except Exception as e:
            print(f"[ERROR] Radiomics failed: {e}")
            return None

    def predict(self, ct_path, radiomics_features):
        print(f"[5/5] Computing prediction...")
        
        if self.model is None or self.scaler is None:
            return "ERR: Model/Scaler missing."

        try:
            radio_scaled = self.scaler.transform(radiomics_features)
        except Exception as e:
            print(f"[ERROR] Mismatch Radiomics! Expecting {self.scaler.n_features_in_}, actual {radiomics_features.shape[1]}.")
            return None

        img = nib.load(ct_path)
        vol_3d = img.get_fdata().astype(np.float32)
        
        if len(vol_3d.shape) == 3:
            vol_3d = np.expand_dims(vol_3d, axis=-1)
        
        slices = []
        depth = vol_3d.shape[2]
        
        for z in range(depth):
            slice_img = vol_3d[:, :, z, :] 
            
            slice_resized = tf.image.resize(slice_img, TARGET_SHAPE_2D).numpy()
            
            if np.sum(slice_resized) > 5.0:
                slices.append(slice_resized)
                
        if len(slices) == 0:
            print("[WARN] No valid slice.")
            return None
            
        slices_array = np.array(slices) 
        radio_array = np.repeat(radio_scaled, len(slices), axis=0)
        
        preds = self.model.predict([slices_array, radio_array], verbose=0)
        
        ttf1_vals = None
        ck7_vals = None

        if isinstance(preds, np.ndarray) and preds.shape[-1] == 2:
             ttf1_vals = preds[:, 0]
             ck7_vals = preds[:, 1]
        elif isinstance(preds, list):
             ttf1_vals = preds[0]
             ck7_vals = preds[1]
        elif isinstance(preds, dict):
             ttf1_vals = preds.get('TTF1')
             ck7_vals = preds.get('CK7')
        else:
             # Fallback
             ttf1_vals = preds
             ck7_vals = np.zeros_like(preds)

        ttf1_score = np.mean(ttf1_vals) if ttf1_vals is not None else 0.0
        ck7_score = np.mean(ck7_vals) if ck7_vals is not None else 0.0

        return {
            "Raw_TTF1": float(ttf1_score),
            "Raw_CK7": float(ck7_score),
            "TTF1_Class": "POZITIVE" if ttf1_score > 0.60 else "Negative",
            "CK7_Class": "POZITIVE" if ck7_score > 0.69 else "Negative"
        }

if __name__ == "__main__":
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    MODEL_FILE = os.path.join(BASE_DIR, "model", "model_2d_efficientnet_v3_FIXED_LR.keras")
    SCALER_FILE = os.path.join(BASE_DIR, "model", "radiomics_scaler.joblib")

    TEMP_DIR = os.path.join(BASE_DIR, "temp_processing")
    os.makedirs(TEMP_DIR, exist_ok=True)

    INPUT_DICOM_DIR = os.path.join(BASE_DIR, "data_pacient", "S0001 48")

    pipeline = LungCancerPipeline(MODEL_FILE, SCALER_FILE)

    if os.path.isdir(INPUT_DICOM_DIR):
        try:
            nifti_path = os.path.join(TEMP_DIR, "pacient_ct.nii.gz")
            pipeline.convert_dicom_to_nifti(INPUT_DICOM_DIR, nifti_path)

            mask_path = os.path.join(TEMP_DIR, "pacient_mask.nii.gz")
            pipeline.generate_lung_mask(nifti_path, mask_path)

            prep_ct, prep_mask = pipeline.preprocess_images(nifti_path, mask_path, TEMP_DIR)
            feats = pipeline.extract_radiomics(prep_ct, prep_mask)

            if feats is not None:
                rezultat = pipeline.predict(prep_ct, feats)
                print(f"Probability TTF1: {rezultat['Raw_TTF1']:.4f}")
                print(f"Probability CK7:  {rezultat['Raw_CK7']:.4f}")
                print("-" * 40)
                print(f"Prediction TTF1:    {rezultat['TTF1_Class']}")
                print(f"Prediction CK7:     {rezultat['CK7_Class']}")
            else:
                print("[ERROR] Radiomics feature extraction failed.")
        except Exception as e:
            import traceback
            print(f"\n[CRITICAL] Error occurred: {e}")
            traceback.print_exc()
    else:
        print(f"[ERROR] Directory {INPUT_DICOM_DIR} does not exist.")