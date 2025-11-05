from dataclasses import dataclass
from typing import List


@dataclass
class Case:
    case_id: str
    patient_name: str
    date: str           # ISO yyyy-mm-dd
    status: str         # Unsegmented / Segmented / Reported
    series_paths: List[str]  # local PNG paths for demo
