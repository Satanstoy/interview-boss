from typing import List, Dict, Any
from pydantic import BaseModel, Field


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
    question_text: str = Field(..., max_length=10000)
    user_answer: str = Field(..., max_length=10000)
    reference_answer: str = Field(..., max_length=10000)


class ProfileUpdateRequest(BaseModel):
    settings: Dict[str, str]


class SplitQuestionRequest(BaseModel):
    original_question: str


class MergeOriginalQuestionRequest(BaseModel):
    original_question: str
    target_id: int
    target_cat1: str = ""
    target_cat2: str = ""


class UploadToBankRequest(BaseModel):
    question_text: str = Field(..., max_length=5000)
    cat1: str = ""
    cat2: str = ""
    tags: str = ""
    difficulty: str = ""
    target: str = "public"
