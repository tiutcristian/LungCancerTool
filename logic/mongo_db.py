import os
import io
import hashlib
import urllib.request
from typing import Any, Dict, List, Optional
from PIL import Image
from pymongo import MongoClient
from bson import ObjectId
import gridfs
import time

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
        if self.cases.find_one({"case_id": case.case_id}):
            print(f"[MongoDB] Case with id {case.case_id} already exists.")
            return None

        doc = {
            "case_id": case.case_id,
            "patient_name": case.patient_name,
            "date": case.date,
            "segmentation_status": case.segmentation_status,
            "ct_series_dir": case.ct_series_dir,
            "ai_result": {},
        }

        res = self.cases.insert_one(doc)
        return str(res.inserted_id)

    def update_case(self, case: Case) -> bool:
        res = self.cases.update_one(
            {"case_id": case.case_id},
            {
                "$set": {
                    "patient_name": case.patient_name,
                    "date": case.date,
                    "segmentation_status": case.segmentation_status,
                    "ct_series_dir": case.ct_series_dir,
                }
            },
        )
        return res.matched_count > 0

    def list_cases(self) -> List[Case]:
        out = []
        for doc in self.cases.find({}):
            out.append(
                Case(
                    case_id=doc.get("case_id"),
                    patient_name=doc.get("patient_name", ""),
                    date=doc.get("date", ""),
                    segmentation_status=doc.get("segmentation_status", ""),
                    ct_series_dir=doc.get("ct_series_dir", ""),
                )
            )
        return out

    def get_case(self, case_id: str) -> Case:
        doc = self.cases.find_one({"case_id": case_id})
        if not doc:
            raise KeyError(f"Case '{case_id}' not found")

        return Case(
            case_id=doc["case_id"],
            patient_name=doc.get("patient_name", ""),
            date=doc.get("date", ""),
            segmentation_status=doc.get("segmentation_status", ""),
            ct_series_dir=doc.get("ct_series_dir", ""),
        )

    def save_ai_result(self, case_id: str, ai_result: Dict[str, Any]) -> bool:
        res = self.cases.update_one(
            {"case_id": case_id},
            {"$set": {"ai_result": ai_result}},
        )
        return res.matched_count > 0

    def get_ai_result(self, case_id: str) -> Dict[str, Any]:
        doc = self.cases.find_one({"case_id": case_id})
        if not doc:
            raise KeyError(f"Case '{case_id}' not found")
        return doc.get("ai_result", {})

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

        if os.path.exists(ref):
            return ref

        target_dir = os.path.join(self.cache_dir, subdir, "assets")
        os.makedirs(target_dir, exist_ok=True)

        try:
            oid = ObjectId(ref)
            grid_out = self.fs.get(oid)
        except Exception as e:
            raise RuntimeError(f"Invalid GridFS ref: {ref}") from e

        filename = grid_out.filename or f"{ref}"
        local_path = os.path.join(target_dir, filename)

        if os.path.exists(local_path):
            return local_path

        with open(local_path, "wb") as f:
            f.write(grid_out.read())

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

    def delete_case(self, case_id: str) -> bool:
        res = self.cases.delete_one({"case_id": case_id})
        return res.deleted_count > 0


    def clean_cache(self, max_age_seconds: int):
        """
        Delete files older than `max_age_seconds` from the cache directory.
        """
        now = time.time()
        for root, dirs, files in os.walk(self.cache_dir):
            for file in files:
                file_path = os.path.join(root, file)
                if os.path.isfile(file_path):
                    if now - os.path.getatime(file_path) > max_age_seconds:
                        try:
                            os.remove(file_path)
                            print(f"Deleted cached file: {file_path}")
                        except Exception as e:
                            print(f"Failed to delete file {file_path}: {e}")