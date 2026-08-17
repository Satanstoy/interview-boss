"""Deterministic scoring for extraction, resume and tagging observations."""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any


def _normalize(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).lower()
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", text, flags=re.UNICODE)


def _text_matches(expected: Any, actual: Any) -> bool:
    expected_text = _normalize(expected)
    actual_text = _normalize(actual)
    if not expected_text or not actual_text:
        return False
    return expected_text in actual_text or actual_text in expected_text


def _assertion(assertion_id: str, passed: bool, evidence: str) -> dict[str, Any]:
    return {"id": assertion_id, "passed": bool(passed), "evidence": evidence}


def _field_value(data: dict[str, Any], path: str) -> Any:
    value: Any = data
    for part in str(path).split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def evaluate_content_trace(
    trace: dict[str, Any], contract: dict[str, Any]
) -> dict[str, Any]:
    """Score structured extraction output without using an LLM."""
    trace = trace if isinstance(trace, dict) else {}
    contract = contract if isinstance(contract, dict) else {}
    data = trace.get("data") if isinstance(trace.get("data"), dict) else {}
    expected_type = contract.get("expected_type")
    type_valid = not expected_type or trace.get("doc_type") == expected_type
    required_fields = [str(field) for field in contract.get("required_fields") or []]
    present_fields = [field for field in required_fields if _field_value(data, field) not in (None, "")]
    field_coverage = round(len(present_fields) / len(required_fields), 4) if required_fields else 1.0

    field_results = []
    for expected in contract.get("field_expectations") or []:
        if not isinstance(expected, dict):
            continue
        path = str(expected.get("path") or "")
        actual = _field_value(data, path)
        matched = _text_matches(expected.get("expected"), actual)
        field_results.append({"path": path, "expected": expected.get("expected"), "actual": actual, "passed": matched})
    field_match_rate = (
        round(sum(item["passed"] for item in field_results) / len(field_results), 4)
        if field_results
        else 1.0
    )

    questions = data.get("具体题目清单") or data.get("questions") or []
    questions = questions if isinstance(questions, list) else []
    expected_questions = [item for item in contract.get("expected_questions") or []]
    matched_expected = [
        expected
        for expected in expected_questions
        if any(_text_matches(expected, actual) for actual in questions)
    ]
    matched_actual = [
        actual
        for actual in questions
        if any(_text_matches(expected, actual) for expected in expected_questions)
    ]
    question_recall = (
        round(len(matched_expected) / len(expected_questions), 4)
        if expected_questions
        else 1.0
    )
    question_precision = (
        round(len(matched_actual) / len(questions), 4)
        if questions
        else 0.0
    )
    serialized = _json_text(data)
    forbidden_content = [
        str(value)
        for value in contract.get("forbidden_content") or []
        if _normalize(value) and _normalize(value) in _normalize(serialized)
    ]
    min_question_count = int(contract.get("min_question_count") or 0)
    schema_valid = isinstance(data, dict) and (
        not expected_type or isinstance(trace.get("doc_type"), str)
    )
    assertions = [
        _assertion("content_schema_valid", schema_valid and type_valid, f"type={trace.get('doc_type')!r}"),
        _assertion("required_fields_present", field_coverage == 1.0, f"missing={sorted(set(required_fields) - set(present_fields))}"),
        _assertion("field_expectations_match", field_match_rate == 1.0, f"matched={field_match_rate}"),
        _assertion("question_recall", question_recall == 1.0 and len(questions) >= min_question_count, f"recall={question_recall}, count={len(questions)}"),
        _assertion("question_precision", question_precision == 1.0 if expected_questions else len(questions) >= min_question_count, f"precision={question_precision}"),
        _assertion("no_forbidden_content", not forbidden_content, f"forbidden={forbidden_content}"),
    ]
    return {
        "metrics": {
            "schema_valid": schema_valid and type_valid,
            "field_coverage": field_coverage,
            "field_match_rate": field_match_rate,
            "question_count": len(questions),
            "question_recall": question_recall,
            "question_precision": question_precision,
            "forbidden_content": forbidden_content,
            "field_results": field_results,
        },
        "assertions": assertions,
    }


def evaluate_resume_trace(
    trace: dict[str, Any], contract: dict[str, Any]
) -> dict[str, Any]:
    """Score resume analysis/optimization for grounding and job alignment."""
    trace = trace if isinstance(trace, dict) else {}
    contract = contract if isinstance(contract, dict) else {}
    points = trace.get("points") or []
    points = points if isinstance(points, list) else []
    optimized_text = str(trace.get("optimized_text") or "")
    combined = _json_text(points) + "\n" + optimized_text
    source_facts = [str(item) for item in contract.get("source_facts") or []]
    target_terms = [str(item) for item in contract.get("target_terms") or []]
    grounded = [fact for fact in source_facts if _normalize(fact) in _normalize(combined)]
    aligned = [term for term in target_terms if _normalize(term) in _normalize(combined)]
    forbidden_claims = [
        claim
        for claim in contract.get("forbidden_claims") or []
        if _normalize(claim) and _normalize(claim) in _normalize(combined)
    ]
    source_coverage = round(len(grounded) / len(source_facts), 4) if source_facts else 1.0
    target_alignment = round(len(aligned) / len(target_terms), 4) if target_terms else 1.0
    min_points = int(contract.get("min_points") or 0)
    assertions = [
        _assertion("resume_output_present", bool(optimized_text.strip()), "优化文本非空" if optimized_text.strip() else "优化文本为空"),
        _assertion("source_facts_grounded", source_coverage == 1.0, f"coverage={source_coverage}, missing={sorted(set(source_facts) - set(grounded))}"),
        _assertion("target_alignment", target_alignment == 1.0, f"alignment={target_alignment}, missing={sorted(set(target_terms) - set(aligned))}"),
        _assertion("no_fabricated_claims", not forbidden_claims, f"forbidden={forbidden_claims}"),
        _assertion("improvement_points_present", len(points) >= min_points, f"points={len(points)}, minimum={min_points}"),
    ]
    return {
        "metrics": {
            "source_fact_coverage": source_coverage,
            "target_alignment": target_alignment,
            "forbidden_claim_count": len(forbidden_claims),
            "improvement_point_count": len(points),
            "optimized_text_length": len(optimized_text),
        },
        "assertions": assertions,
    }


def evaluate_tagging_trace(
    trace: dict[str, Any], contract: dict[str, Any]
) -> dict[str, Any]:
    """Score question labels against a frozen taxonomy and expected labels."""
    trace = trace if isinstance(trace, dict) else {}
    contract = contract if isinstance(contract, dict) else {}
    rows = trace.get("tagged_rows") or []
    rows = rows if isinstance(rows, list) else []
    taxonomy = contract.get("taxonomy") or {}
    valid_rows = []
    invalid_rows = []
    for row in rows:
        if not isinstance(row, list) or len(row) < 8:
            invalid_rows.append(row)
            continue
        cat1, cat2, difficulty = row[4], row[5], row[7]
        valid_cat2 = taxonomy.get(cat1) or []
        if cat1 not in taxonomy or (valid_cat2 and cat2 not in valid_cat2) or not difficulty:
            invalid_rows.append(row)
        else:
            valid_rows.append(row)
    taxonomy_validity = round(len(valid_rows) / len(rows), 4) if rows else 0.0

    expected_labels = contract.get("expected_labels") or {}
    label_results = []
    for row in rows:
        if not isinstance(row, list) or len(row) < 8:
            continue
        expected = expected_labels.get(str(row[3]))
        if not expected:
            continue
        checks = {
            key: row[index] == value
            for key, index in (("一级大类", 4), ("二级子类", 5), ("难度标签", 7))
            if (value := expected.get(key)) is not None
        }
        label_results.append({"question": row[3], "passed": all(checks.values()), "checks": checks})
    classification_accuracy = (
        round(sum(item["passed"] for item in label_results) / len(label_results), 4)
        if label_results
        else 1.0
    )
    assertions = [
        _assertion("tagging_schema_valid", not invalid_rows and bool(rows), f"rows={len(rows)}, invalid={len(invalid_rows)}"),
        _assertion("taxonomy_valid", taxonomy_validity == 1.0, f"validity={taxonomy_validity}"),
        _assertion("expected_labels_match", classification_accuracy == 1.0, f"accuracy={classification_accuracy}"),
    ]
    return {
        "metrics": {
            "row_count": len(rows),
            "taxonomy_validity": taxonomy_validity,
            "classification_accuracy": classification_accuracy,
            "label_results": label_results,
        },
        "assertions": assertions,
    }
