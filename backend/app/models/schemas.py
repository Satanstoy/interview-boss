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


class DeleteOriginalQuestionRequest(BaseModel):
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


class UpdateQuestionRequest(BaseModel):
    question: str = Field(None, max_length=5000)
    cat1: str = Field(None, max_length=200)
    cat2: str = Field(None, max_length=200)
    tags: str = Field(None, max_length=500)
    difficulty: str = Field(None, max_length=50)


class CodingSubmitRequest(BaseModel):
    problem_id: int
    language: str = Field(..., max_length=20)
    code: str = Field(..., max_length=50000)
    mode: str = Field("full_review", max_length=20)
    parent_submission_id: int = None


class CodingProblemCreateRequest(BaseModel):
    title: str = Field(..., max_length=200)
    description: str = Field(..., max_length=20000)
    difficulty: str = Field("medium", max_length=20)
    tags: str = Field("[]", max_length=500)
    expected_complexity: str = Field("", max_length=100)
    source: str = Field("", max_length=200)
    supported_languages: str = Field('["python","c","java"]', max_length=500)
