from typing import Dict, Any, List

from model.models import Case
from logic.mongo_db import MongoDB

_db = MongoDB()


def get_initial_cases() -> List[Case]:
    return _db.list_cases()


def run_ai(case: Case) -> Dict[str, Any]:
    return _db.get_ai_result(case.case_id)


def add_case(case: Case) -> str:
    return _db.insert_case(case)


def update_case(case: Case) -> bool:
    return _db.update_case(case)


def delete_case(case_id: str) -> bool:
    return _db.delete_case(case_id)