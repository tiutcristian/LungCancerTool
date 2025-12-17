import os
import io
import hashlib
import urllib.request
from typing import Any, Dict, List, Optional
from PIL import Image
from pymongo import MongoClient
from bson import ObjectId
import gridfs

from model.models import Case

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass


def _is_url(s: str) -> bool:
    return s.startswith("http://") or s.startswith("https://")


def _sha1(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


class MongoDB:
    def __init__(
        self,
        mongo_uri: Optional[str] = None,
        db_name: Optional[str] = None,
        cases_collection: Optional[str] = None,
        cache_dir: Optional[str] = None,
    ):
        self.mongo_uri = mongo_uri or os.getenv("MONGO_URI")
        self.db_name = db_name or os.getenv("MONGO_DB_NAME", "lung_cancer_tool")
        self.cases_collection = cases_collection or os.getenv("MONGO_CASES_COLLECTION", "cases")
        self.cache_dir = cache_dir or os.getenv("MONGO_CACHE_DIR", os.path.join(os.getcwd(), ".mongo_cache"))

        if not self.mongo_uri:
            raise RuntimeError("Missing MONGO_URI in environment or .env file")

        os.makedirs(self.cache_dir, exist_ok=True)

        self.client = MongoClient(self.mongo_uri)
        self.db = self.client[self.db_name]
        self.cases = self.db[self.cases_collection]
        self.fs = gridfs.GridFS(self.db)

    # -------------------------------------------------------------------------
    # CRUD OPERATIONS
    # -------------------------------------------------------------------------

    def insert_case(self, case: Case) -> Optional[str]:
        """
        Insert a new Case into MongoDB, storing images in GridFS.

        Args:
            case (Case): the case object to insert

        Returns:
            str: the inserted document ID (string form), or None if case_id exists
        """
        existing = self.cases.find_one({"case_id": case.case_id})
        if existing:
            print(f"[MongoDB] Case with id {case.case_id} already exists, skipping insert.")
            return None

        # Upload images to GridFS and store file_ids
        file_ids = []
        for img_path in case.ct_images:
            if not os.path.exists(img_path):
                img_path = self._resolve_image_to_local_path(img_path, subdir="ct")

            with open(img_path, "rb") as f:
                file_id = self.fs.put(f, filename=os.path.basename(img_path))
                file_ids.append(str(file_id))

        doc = {
            "case_id": case.case_id,
            "patient_name": case.patient_name,
            "date": case.date,
            "segmentation_status": case.segmentation_status,
            "ct_images": file_ids,  # Store file_ids instead of paths
            "ai_result": {},  # empty at first
        }

        result = self.cases.insert_one(doc)
        print(f"[MongoDB] Inserted case {case.case_id} with _id={result.inserted_id}")
        return str(result.inserted_id)


    def update_case(self, case: Case) -> bool:
        """
        Update an existing Case in MongoDB.

        Args:
            case (Case): the case object to update
        Returns:
            bool: True if the case was updated, False if not found
        """
        result = self.cases.update_one(
            {"case_id": case.case_id},
            {
                "$set": {
                    "patient_name": case.patient_name,
                    "date": case.date,
                    "segmentation_status": case.segmentation_status,
                    "ct_images": case.ct_images,
                }
            },
        )
        if result.matched_count == 0:
            print(f"[MongoDB] Case with id {case.case_id} not found, cannot update.")
            return False
        print(f"[MongoDB] Updated case {case.case_id}, modified_count={result.modified_count}")
        return True

    def list_cases(self) -> List[Case]:
        out: List[Case] = []
        for doc in self.cases.find({}, projection=None):
            case_id = str(doc.get("case_id") or doc.get("_id"))
            patient_name = doc.get("patient_name", "")
            date = doc.get("date", "")
            segmentation_status = doc.get("segmentation_status", "")
            ct_refs = doc.get("ct_images", []) or []
            ct_local_paths = [self._resolve_image_to_local_path(ref, subdir="ct") for ref in ct_refs]

            out.append(
                Case(
                    case_id=case_id,
                    patient_name=patient_name,
                    date=date,
                    segmentation_status=segmentation_status,
                    ct_images=ct_local_paths,  # Resolve file_ids to local paths
                )
            )
        return out

    def get_ai_result(self, case_id: str) -> Dict[str, Any]:
        doc = self._find_case_doc(case_id)
        ai = doc.get("ai_result") or {}
        biomarkers = ai.get("biomarkers", []) or []
        explanation = ai.get("explanation", "") or ""
        heatmap_ref = ai.get("heatmap")
        heatmap_img = None
        if heatmap_ref:
            heatmap_img = self._load_image_as_pil(heatmap_ref).convert("RGBA")
        return {"biomarkers": biomarkers, "explanation": explanation, "heatmap": heatmap_img}

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------

    def _find_case_doc(self, case_id: str) -> Dict[str, Any]:
        doc = self.cases.find_one({"case_id": case_id})
        if doc:
            return doc
        doc = self.cases.find_one({"_id": case_id})
        if doc:
            return doc
        try:
            oid = ObjectId(case_id)
            doc = self.cases.find_one({"_id": oid})
            if doc:
                return doc
        except Exception:
            pass
        raise KeyError(f"Case '{case_id}' not found in MongoDB collection '{self.cases_collection}'.")

    def _resolve_image_to_local_path(self, ref: str, subdir: str) -> str:
        if not ref:
            return ref

        # 1. If it's already a local path, just return it
        if os.path.exists(ref):
            return ref

        target_dir = os.path.join(self.cache_dir, subdir, "assets")
        os.makedirs(target_dir, exist_ok=True)

        # Use ref as filename only if it's an ObjectId
        filename = f"{ref}.png"
        local_path = os.path.join(target_dir, filename)

        if os.path.exists(local_path):
            return local_path

        raw = self._load_bytes(ref)
        with open(local_path, "wb") as f:
            f.write(raw)

        return local_path

    def _load_image_as_pil(self, ref: str) -> Image.Image:
        raw = self._load_bytes(ref)
        return Image.open(io.BytesIO(raw))

    def _load_bytes(self, ref: str) -> bytes:
        if _is_url(ref):
            req = urllib.request.Request(ref, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read()
        if os.path.exists(ref):
            with open(ref, "rb") as f:
                return f.read()
        try:
            oid = ObjectId(ref)
        except Exception as e:
            raise ValueError(
                "Image ref must be a URL, an existing local path, or a GridFS ObjectId string. "
                f"Got: {ref}"
            ) from e
        grid_out = self.fs.get(oid)
        return grid_out.read()

    def delete_case(self, case_id):
        result = self.cases.delete_one({"case_id": case_id})
        if result.deleted_count == 0:
            print(f"[MongoDB] Case with id {case_id} not found, cannot delete.")
            return False
        print(f"[MongoDB] Deleted case {case_id}.")
        return True


