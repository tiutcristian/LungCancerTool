import numpy as np
import pydicom
from pydicom.pixel_data_handlers.util import apply_modality_lut, apply_voi_lut


def dicom_to_gray_np(path: str) -> np.ndarray:
    """
    Convert DICOM to normalized uint8 grayscale numpy array (for AI).
    """
    ds = pydicom.dcmread(path, force=True)
    arr = ds.pixel_array.astype(np.float32)

    try:
        arr = apply_modality_lut(arr, ds)
    except Exception:
        pass

    try:
        arr = apply_voi_lut(arr, ds)
    except Exception:
        pass

    if str(getattr(ds, "PhotometricInterpretation", "")).upper() == "MONOCHROME1":
        arr = arr.max() - arr

    # normalize to 0–255
    arr -= arr.min()
    if arr.max() > 0:
        arr /= arr.max()
    arr *= 255.0

    return arr.astype(np.uint8)
