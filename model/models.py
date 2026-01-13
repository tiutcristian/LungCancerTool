from dataclasses import dataclass
from typing import List


@dataclass
class Case:
    case_id: str
    patient_name: str
    date: str
    segmentation_status: str
    ct_series_dir: str