import os
import random
from typing import Dict, Any
from PIL import Image, ImageDraw, ImageFilter
from models import Case

ROOT_DIR = os.path.dirname(__file__)
ASSETS_DIR = os.path.join(ROOT_DIR, "assets")


def _asset(name: str) -> str:
    return os.path.join(ASSETS_DIR, name)


def get_initial_cases():
    return [
        Case(
            "LC-001",
            "John Doe",
            "2025-10-01",
            "Unsegmented",
            [_asset("sample_ct_1.png"), _asset("sample_ct_2.png")],
        ),
        Case(
            "LC-002",
            "Jane Smith",
            "2025-10-03",
            "Segmented",
            [_asset("sample_ct_2.png")],
        ),
    ]


def _fake_heatmap(size):
    """Return a semi-transparent red heatmap blob image, same size as CT."""
    w, h = size
    heat = Image.new("RGBA", (w, h), (255, 0, 0, 0))
    draw = ImageDraw.Draw(heat)
    # 2–3 „zone fierbinți” random
    for _ in range(random.randint(2, 3)):
        cx, cy = random.randint(w // 5, 4 * w // 5), random.randint(h // 5, 4 * h // 5)
        rx, ry = random.randint(w // 8, w // 4), random.randint(h // 8, h // 4)
        for i in range(6):
            alpha = int(40 - i * 6)  # scade spre margine
            draw.ellipse([cx - rx + i*4, cy - ry + i*4, cx + rx - i*4, cy + ry - i*4],
                         fill=(255, 0, 0, max(alpha, 0)))
    return heat.filter(ImageFilter.GaussianBlur(radius=18))


def mock_run_ai(case: Case) -> Dict[str, Any]:
    """Returnează biomarkeri + explicație + heatmap RGBA pentru blend."""
    biomarkers = [
        {"name": "Malignancy probability", "value": random.uniform(0.3, 0.95)},
        {"name": "Lymph node involvement", "value": random.uniform(0.1, 0.8)},
        {"name": "Metastasis risk", "value": random.uniform(0.05, 0.7)},
    ]
    explanation = (
        f"(Mock) Pentru cazul {case.case_id}, probabilitatea mai mare de malignitate "
        "este influențată de dimensiunea nodulului, localizarea în lobul superior "
        "și spiculații."
    )
    heatmap = _fake_heatmap((512, 512))  # dimensiune de lucru; va fi redimensionat la afișare
    return {"biomarkers": biomarkers, "explanation": explanation, "heatmap": heatmap}
