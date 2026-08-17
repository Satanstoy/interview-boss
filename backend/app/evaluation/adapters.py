"""Target Adapter boundary for evaluation execution."""

from __future__ import annotations

from typing import Any, Protocol


class TargetAdapter(Protocol):
    async def prepare(self, case_snapshot: dict[str, Any], target_release: dict[str, Any]) -> Any:
        ...

    async def run(self, prepared_case: Any, target_release: dict[str, Any]) -> Any:
        ...

    async def observe(self, raw_result: Any) -> dict[str, Any]:
        ...


class AdapterNotConfigured(RuntimeError):
    """Raised when a target type has no registered evaluation adapter."""


_ADAPTERS: dict[str, TargetAdapter] = {}


def register_target_adapter(target_type: str, adapter: TargetAdapter) -> None:
    _ADAPTERS[target_type] = adapter


def get_target_adapter(target_type: str) -> TargetAdapter:
    if target_type not in _ADAPTERS and target_type == "interview":
        from app.evaluation.interview_adapter import InterviewE2EAdapter

        _ADAPTERS[target_type] = InterviewE2EAdapter()
    if target_type not in _ADAPTERS and target_type in {"experience_extraction", "jd_extraction", "question_tagging"}:
        from app.evaluation.content_adapters import ContentExtractionAdapter, QuestionTaggingAdapter

        _ADAPTERS["experience_extraction"] = ContentExtractionAdapter("interview")
        _ADAPTERS["jd_extraction"] = ContentExtractionAdapter("jd")
        _ADAPTERS["question_tagging"] = QuestionTaggingAdapter()
    if target_type not in _ADAPTERS and target_type == "resume_analysis":
        from app.evaluation.resume_adapter import ResumeAnalysisAdapter

        _ADAPTERS[target_type] = ResumeAnalysisAdapter()
    try:
        return _ADAPTERS[target_type]
    except KeyError as exc:
        raise AdapterNotConfigured(f"未配置评测目标适配器: {target_type}") from exc
