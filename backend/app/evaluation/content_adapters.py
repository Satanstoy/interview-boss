"""Adapters for the production document extraction and question tagging flows."""

from __future__ import annotations

import os
from typing import Any

from app.agents.submit.classify import classify_node
from app.agents.submit.extract import extract_node
from app.evaluation.content_scoring import (
    evaluate_content_trace,
    evaluate_tagging_trace,
)


def _user_id(target_release: dict[str, Any]) -> int:
    return int(target_release.get("created_by") or os.environ.get("EVAL_USER_ID", "1"))


def _target_model(target_release: dict[str, Any]) -> str:
    return str((target_release.get("manifest") or {}).get("model") or "")


class ContentExtractionAdapter:
    """Run the same extraction node used by Interview/JD import."""

    def __init__(self, content_type: str):
        self.content_type = content_type

    async def prepare(
        self, case_snapshot: dict[str, Any], target_release: dict[str, Any]
    ) -> dict[str, Any]:
        return {
            "raw_text": str(case_snapshot.get("raw_text") or ""),
            "content_type_hint": self.content_type,
            "image_data": case_snapshot.get("image_data") or [],
            "contract": case_snapshot.get("_eval_contract") or {},
        }

    async def run(
        self, prepared_case: dict[str, Any], target_release: dict[str, Any]
    ) -> dict[str, Any]:
        state = {
            "doc_type": prepared_case["content_type_hint"],
            "raw_text": prepared_case["raw_text"],
            "content_type_hint": prepared_case["content_type_hint"],
            "image_data": prepared_case["image_data"],
            "user_id": _user_id(target_release),
            "_eval_model": _target_model(target_release),
            "_eval_temperature": float(
                (target_release.get("manifest") or {}).get("temperature", 0.1)
            ),
        }
        result = await extract_node(state)
        return {
            "status": "succeeded",
            "doc_type": result.get("doc_type") or self.content_type,
            "data": result.get("extracted_data") or {},
            "quality": result.get("extraction_quality"),
            "errors": result.get("error") and [result["error"]] or [],
            "contract": prepared_case["contract"],
        }

    async def observe(self, raw_result: dict[str, Any]) -> dict[str, Any]:
        trace = {
            "doc_type": raw_result.get("doc_type"),
            "data": raw_result.get("data") or {},
        }
        scored = evaluate_content_trace(trace, raw_result.get("contract") or {})
        assertions = scored["assertions"]
        errors = raw_result.get("errors") or []
        if errors:
            assertions = assertions + [
                {"id": "production_flow_completed", "passed": False, "evidence": "; ".join(errors[:2])}
            ]
        return {
            "status": "succeeded" if not errors else "failed",
            "payload": {
                **trace,
                "quality": raw_result.get("quality"),
                "metrics": scored["metrics"],
            },
            "hard_assertions": assertions,
            "contract_violations": [item["id"] for item in assertions if not item["passed"]],
        }


class QuestionTaggingAdapter:
    """Run the production question classification node against a frozen taxonomy."""

    async def prepare(
        self, case_snapshot: dict[str, Any], target_release: dict[str, Any]
    ) -> dict[str, Any]:
        return {
            "questions": list(case_snapshot.get("questions") or []),
            "company": str(case_snapshot.get("company") or "未提供"),
            "round": str(case_snapshot.get("round") or "未提供"),
            "taxonomy": case_snapshot.get("taxonomy") or {},
            "contract": case_snapshot.get("_eval_contract") or {},
        }

    async def run(
        self, prepared_case: dict[str, Any], target_release: dict[str, Any]
    ) -> dict[str, Any]:
        taxonomy = prepared_case["taxonomy"]
        if "categories" not in taxonomy:
            taxonomy = {
                "job_position": "evaluation",
                "categories": [
                    {"cat1": cat1, "children": children}
                    for cat1, children in taxonomy.items()
                ],
            }
        state = {
            "user_id": _user_id(target_release),
            "extracted_data": {
                "公司": prepared_case["company"],
                "面试轮次": prepared_case["round"],
                "具体题目清单": prepared_case["questions"],
            },
            "saved_url": "eval://question-tagging",
            "taxonomy_config": taxonomy,
            "_eval_model": _target_model(target_release),
        }
        result = await classify_node(state)
        return {
            "status": "succeeded",
            "tagged_rows": result.get("tagged_rows") or [],
            "quality": result.get("tagging_quality"),
            "contract": prepared_case["contract"],
        }

    async def observe(self, raw_result: dict[str, Any]) -> dict[str, Any]:
        trace = {"tagged_rows": raw_result.get("tagged_rows") or []}
        scored = evaluate_tagging_trace(trace, raw_result.get("contract") or {})
        assertions = scored["assertions"]
        return {
            "status": "succeeded" if raw_result.get("status") == "succeeded" else "failed",
            "payload": {**trace, "quality": raw_result.get("quality"), "metrics": scored["metrics"]},
            "hard_assertions": assertions,
            "contract_violations": [item["id"] for item in assertions if not item["passed"]],
        }
