"""Evaluate matching prompts without creating uploads or question-bank rows.

Run with a configured LLM environment:
PYTHONPATH=backend python backend/scripts/evaluate_import_pair_cases.py \
    backend/tests/fixtures/import_cases/nio_agent_first_round.json
Optional second argument loads a prompts.py snapshot for before/after comparison.
Only use non-private fixture text. Calls use the configured global provider.
"""

import asyncio
import json
import runpy
import sys
import time
from pathlib import Path

from app.services.llm import _call_llm_with_retry, _extract_json
from app.services.clustering import prompts as current


async def main():
    fixture = json.loads(Path(sys.argv[1]).read_text())
    prompts = runpy.run_path(sys.argv[2]) if len(sys.argv) > 2 else vars(current)
    semaphore = asyncio.Semaphore(3)

    async def evaluate(case):
        async with semaphore:
            start = time.monotonic()
            prompt = prompts["MATCH_EXISTING_PROMPT"].format(
                existing_clusters="[200] " + case["existing_question"],
                new_questions="[100] " + case["new_question"],
                count=1,
            )
            try:
                response = await _call_llm_with_retry(
                    prompt, response_format={"type": "json_object"},
                    llm_scope="global", temperature=0,
                )
                raw = _extract_json(response)
                matches = raw["matches"]
                if not isinstance(matches, list):
                    raise ValueError("matches must be a list")
                for match in matches:
                    if str(match.get("new_id")) != "100" or str(
                        match.get("cluster_id", match.get("target_id"))
                    ) != "200":
                        raise ValueError("match references an unknown question")
                actual = bool(matches)
                return {
                    **case, "actual_merge": actual,
                    "passed": actual == case["should_merge"], "raw": raw,
                    "seconds": round(time.monotonic() - start, 2),
                }
            except Exception as exc:
                return {"id": case["id"], "error": type(exc).__name__, "passed": False}

    results = await asyncio.gather(*(evaluate(case) for case in fixture["pairs"]))
    passed = sum(case["passed"] for case in results)
    print(json.dumps({"cases": results, "passed": passed, "total": len(results)},
                     ensure_ascii=False, indent=2))
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
