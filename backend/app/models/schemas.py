from typing import List, Dict, Any, Optional, Literal
from pydantic import BaseModel, Field, model_validator


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
    force: bool = False


class EvaluateAnswerRequest(BaseModel):
    question_id: int
    question_text: str = Field(..., max_length=10000)
    user_answer: str = Field(..., max_length=10000)
    reference_answer: str = Field(..., max_length=10000)
    model: Optional[str] = Field(None, max_length=100)


class PracticeReviewRequest(BaseModel):
    question_id: int = Field(..., gt=0)
    rating: Literal["again", "hard", "good", "easy"]
    score: Optional[int] = Field(None, ge=0, le=100)
    answer_revealed: bool = True


class PracticeDeckCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    description: str = Field("", max_length=500)
    visibility: Literal["private", "public"] = "private"


class PracticeDeckUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=80)
    description: Optional[str] = Field(None, max_length=500)
    visibility: Optional[Literal["private", "public"]] = None


class PracticeDeckItemRequest(BaseModel):
    question_id: int = Field(..., gt=0)


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
    coding_mode: str = Field("leetcode", max_length=20)
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


class CodingImportRequest(BaseModel):
    prompt: str = Field("", max_length=5000)
    markdown: str = Field(..., min_length=1, max_length=100000)
    filename: str = Field("导入题目.md", max_length=255)
    playlist_id: Optional[int] = Field(None, ge=1)


class CodingPlaylistCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    description: str = Field("", max_length=500)


class CodingPlaylistItemRequest(BaseModel):
    problem_id: int


class CodingPlaylistMoveRequest(BaseModel):
    direction: Literal["up", "down"]


class DistributionPreferenceRequest(BaseModel):
    mode: Literal["system_default", "selected_experience", "custom"] = "system_default"
    target_question_count: Optional[int] = Field(None, ge=1, le=50)
    custom_distribution: Optional[Dict[str, float]] = None
    selected_experience_id: Optional[int] = None
    style_strength: Literal["light", "normal", "strong"] = "normal"

    @model_validator(mode="after")
    def validate_distribution(self):
        keys = {
            "project_followup",
            "knowledge_probe",
            "algorithm_coding",
            "system_design",
            "behavioral",
        }
        if self.mode == "custom":
            if set((self.custom_distribution or {}).keys()) != keys:
                raise ValueError("custom_distribution 必须包含全部五类题型")
            if any(
                value < 0 or value > 1 for value in self.custom_distribution.values()
            ):
                raise ValueError("题型比例必须在 0 到 1 之间")
            if abs(sum(self.custom_distribution.values()) - 1.0) > 1e-6:
                raise ValueError("题型比例之和必须为 1")
        if self.mode == "selected_experience" and self.selected_experience_id is None:
            raise ValueError("selected_experience 模式必须选择面经")
        return self


class CreateConversationRequest(BaseModel):
    mode: str = Field(..., pattern="^(jd_resume|free_practice)$")
    title: Optional[str] = None
    jd_id: Optional[int] = None
    resume_text: Optional[str] = None
    difficulty: Optional[str] = Field(None, pattern="^(junior|mid|senior|staff_plus)$")
    experience_id: Optional[int] = None
    distribution_override: Optional[DistributionPreferenceRequest] = None
    first_message: Optional[str] = Field(None, min_length=1, max_length=10000)
