"""Adapter for the production resume optimization flow."""

from __future__ import annotations

import os
from typing import Any

from app.core.prompts import (
    build_resume_optimize_points_prompt,
    build_resume_optimize_text_prompt,
)
from app.evaluation.content_scoring import evaluate_resume_trace
from app.services.llm import (
    _call_llm_with_retry_messages,
    _extract_json,
    stream_llm_messages,
)


def _user_id(target_release: dict[str, Any]) -> int:
    return int(target_release.get("created_by") or os.environ.get("EVAL_USER_ID", "1"))


class ResumeAnalysisAdapter:
    """Evaluate resume grounding and job-targeted optimization as one output."""

    async def prepare(
        self, case_snapshot: dict[str, Any], target_release: dict[str, Any]
    ) -> dict[str, Any]:
        return {
            "resume_text": str(case_snapshot.get("resume_text") or ""),
            "position": str(case_snapshot.get("position") or ""),
            "contract": case_snapshot.get("_eval_contract") or {},
        }

    async def run(
        self, prepared_case: dict[str, Any], target_release: dict[str, Any]
    ) -> dict[str, Any]:
        model = str((target_release.get("manifest") or {}).get("model") or "")
        user_id = _user_id(target_release)
        points_prompt = build_resume_optimize_points_prompt(
            prepared_case["resume_text"], prepared_case["position"]
        )
        points_raw = await _call_llm_with_retry_messages(
            [{"role": "user", "content": points_prompt}],
            user_id=user_id,
            model=model or None,
            temperature=0.3,
            response_format={"type": "json_object"},
        )
        parsed_points = _extract_json(points_raw)
        points = parsed_points if isinstance(parsed_points, list) else parsed_points.get("points", [])
        points = points if isinstance(points, list) else []

        text_prompt = build_resume_optimize_text_prompt(
            prepared_case["resume_text"], prepared_case["position"]
        )
        text_chunks = []
        async for chunk in stream_llm_messages(
            [{"role": "user", "content": text_prompt}],
            user_id=user_id,
            model=model or None,
            temperature=0.4,
        ):
            text_chunks.append(str(chunk))
        optimized_text = "".join(text_chunks)
        return {
            "status": "succeeded" if optimized_text.strip() else "failed",
            "points": points,
            "optimized_text": optimized_text,
            "contract": prepared_case.get("contract") or {},
        }

    async def observe(self, raw_result: dict[str, Any]) -> dict[str, Any]:
        trace = {
            "points": raw_result.get("points") or [],
            "optimized_text": raw_result.get("optimized_text") or "",
        }
        scored = evaluate_resume_trace(trace, raw_result.get("contract") or {})
        assertions = scored["assertions"]
        return {
            "status": "succeeded" if raw_result.get("status") == "succeeded" else "failed",
            "payload": {**trace, "metrics": scored["metrics"]},
            "hard_assertions": assertions,
            "contract_violations": [item["id"] for item in assertions if not item["passed"]],
        }
