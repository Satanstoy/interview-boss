from typing import List, Dict, Any
from pydantic import BaseModel


class GenericUpdateRequest(BaseModel):
    table_name: str
    record_id: int
    update_data: Dict[str, Any]


class BatchDataDeleteRequest(BaseModel):
    file_type: str  # "jd" or "interview"
    ids: List[int]


class BatchDeleteRequest(BaseModel):
    ids: List[int]


class BatchGenerateAnswersRequest(BaseModel):
    ids: List[int]


class EvaluateAnswerRequest(BaseModel):
    question_id: int
    question_text: str
    user_answer: str
    reference_answer: str


class ProfileUpdateRequest(BaseModel):
    settings: Dict[str, str]
