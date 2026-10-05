"""Compare AC-011's real first-pass and recovery SQLite/provider traces."""

from __future__ import annotations

import json
import sys


def _load(path: str) -> dict:
    with open(path, encoding="utf-8") as stream:
        return json.load(stream)


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: assert_ac011_answer_trace.py FIRST.json FINAL.json")
    first = _load(sys.argv[1])
    final = _load(sys.argv[2])
    if first["phase"] != "first" or final["phase"] != "final":
        raise AssertionError("phase markers do not match first/final evidence")
    if first["error_code"] != "UPSTREAM_UNAVAILABLE":
        raise AssertionError(
            f"expected a retryable upstream error category, got {first['error_code']}"
        )
    if first["import_id"] != final["import_id"] or first["interview_id"] != final["interview_id"]:
        raise AssertionError("recovery changed root or interview identity")

    first_answers = {int(row["question_id"]): row for row in first["answers"]}
    final_answers = {int(row["question_id"]): row for row in final["answers"]}
    first_success_ids = {
        question_id for question_id, row in first_answers.items() if row["status"] == "succeeded"
    }
    first_failed_ids = {
        question_id for question_id, row in first_answers.items() if row["status"] == "failed"
    }
    if len(first_success_ids) != 8 or len(first_failed_ids) != 2:
        raise AssertionError(f"expected 8/2 first pass, got {len(first_success_ids)}/{len(first_failed_ids)}")
    if set(final_answers) != set(first_answers) or any(
        row["status"] != "succeeded" for row in final_answers.values()
    ):
        raise AssertionError("final answer set is not the same ten fully succeeded questions")

    # Preserve all previously completed answer work byte for byte, including its
    # question, answer output, checkpoint content, and output hash.
    for question_id in first_success_ids:
        before = first_answers[question_id]
        after = final_answers[question_id]
        for field in ("question", "ai_answer", "result_json", "output_hash"):
            if before[field] != after[field]:
                raise AssertionError(
                    f"successful question {question_id} changed {field} during retry"
                )
        if before["job_id"] != after["job_id"]:
            raise AssertionError(f"successful question {question_id} was assigned new answer work")

    first_resolutions = {int(row["detail_id"]): row for row in first["resolutions"]}
    final_resolutions = {int(row["detail_id"]): row for row in final["resolutions"]}
    if set(first_resolutions) != set(final_resolutions):
        raise AssertionError("resolution detail set changed during retry")
    for detail_id, before in first_resolutions.items():
        after = final_resolutions[detail_id]
        for field in ("resolution_id", "canonical_id", "canonical_scope", "status"):
            if before[field] != after[field]:
                raise AssertionError(f"detail {detail_id} resolution changed {field}")

    first_attempt_jobs = [row for row in first["answer_jobs"] if int(row["attempt_no"]) == 1]
    retry_jobs = [row for row in final["answer_jobs"] if int(row["attempt_no"]) == 2]
    retry_question_ids = {int(row["question_id"]) for row in retry_jobs}
    if len(first_attempt_jobs) != 10 or retry_question_ids != first_failed_ids or len(retry_jobs) != 2:
        raise AssertionError(
            f"retry must enqueue only the two failed question IDs; got {sorted(retry_question_ids)}"
        )

    before_calls = first["provider_physical_request_counts"]
    after_calls = final["provider_physical_request_counts"]
    for question_id, row in first_answers.items():
        marker = str(row["question"]).split()[0]
        before = int(before_calls.get(marker, 0))
        after = int(after_calls.get(marker, 0))
        expected_delta = 1 if question_id in first_failed_ids else 0
        if after - before != expected_delta:
            raise AssertionError(
                f"physical provider calls for {marker}: expected retry delta {expected_delta}, got {after - before}"
            )

    print(
        json.dumps(
            {
                "status": "passed",
                "import_id": first["import_id"],
                "first_pass": {"answered": 8, "failed": 2},
                "retry_question_ids": sorted(retry_question_ids),
                "preserved_question_ids": sorted(first_success_ids),
                "preserved_resolution_ids": sorted(
                    int(row["resolution_id"]) for row in first_resolutions.values()
                ),
                "provider_retry_deltas": {
                    str(row["question"]).split()[0]: int(
                        after_calls.get(str(row["question"]).split()[0], 0)
                    )
                    - int(before_calls.get(str(row["question"]).split()[0], 0))
                    for row in first["answers"]
                },
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
