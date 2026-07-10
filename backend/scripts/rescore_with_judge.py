#!/usr/bin/env python3
"""Re-score existing eval records with LLM judge.

Usage:
    PYTHONPATH=backend python3 backend/scripts/rescore_with_judge.py [--scenario NAME ...]

Reads the latest JSON eval file per scenario from backend/data/evaluations/,
runs LLM judge on the existing conversation records, and updates the JSON.
No need to re-run the E2E conversation.
"""

import argparse
import glob
import json
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Re-score eval records with LLM judge")
    parser.add_argument(
        "--scenario",
        action="append",
        help="Scenario ID to rescore (default: all found in evaluations/)",
    )
    parser.add_argument("--model", default=None, help="Judge LLM model override")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    scripts_dir = str(Path(__file__).resolve().parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)

    from eval_framework.scenarios import SCENARIOS
    from eval_framework.types import JudgeLLMConfig
    from eval_framework.scoring import llm_score_scenario

    # Resolve judge config from env
    import os

    api_key = os.getenv("OPENAI_API_KEY", "")
    base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    model = args.model or os.getenv("LLM_MODEL_NAME", "mimo-v2.5")

    if not api_key:
        print("Error: OPENAI_API_KEY not set", file=sys.stderr)
        return 1

    judge_config = JudgeLLMConfig(
        api_key=api_key,
        base_url=base_url,
        model=model,
        timeout=120,
    )

    # Find scenarios to rescore
    eval_dir = Path("backend/data/evaluations")
    if args.scenario:
        scenario_ids = args.scenario
    else:
        # Auto-detect from files
        scenario_ids = sorted(
            set(
                f.name.split("_", 2)[1]
                for f in eval_dir.glob("eval_*_*.json")
                if not f.name.startswith("eval_unified")
            )
        )

    if not scenario_ids:
        print("No eval files found", file=sys.stderr)
        return 1

    results = {}
    for sid in scenario_ids:
        files = sorted(eval_dir.glob(f"eval_{sid}_*.json"))
        if not files:
            print(f"  {sid}: no eval file found, skipping")
            continue

        latest = files[-1]
        with open(latest) as f:
            data = json.load(f)

        turns = data.get("turns", [])
        metrics = data.get("metrics", {})
        scenario = SCENARIOS.get(sid)

        if not scenario:
            print(f"  {sid}: scenario not in SCENARIOS, skipping")
            continue

        print(f"=== {sid} ({len(turns)} turns) ===")
        try:
            judge_result = llm_score_scenario(scenario, turns, metrics, judge_config)

            # Update the JSON with judge results
            data["llm_judge_scores"] = judge_result
            with open(latest, "w") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            # Print summary
            overall = judge_result.get("overall_score", "?")
            critical = judge_result.get("critical_issues", [])
            highlights = judge_result.get("highlights", [])
            print(f"  Overall: {overall}/10")
            if critical:
                print(f"  Critical: {critical[0][:100]}")
            if highlights:
                print(f"  Highlight: {highlights[0][:100]}")

            for key, item in judge_result.get("items", {}).items():
                status = "✅" if item.get("passed") else "❌"
                score = item.get("score", "?")
                reasoning = item.get("reasoning", "")[:80]
                print(f"  {status} {key}: {score} | {reasoning}")

            results[sid] = judge_result
        except Exception as e:
            print(f"  Error: {e}")
        print()

    # Write unified summary
    if results:
        summary_path = eval_dir / "rescore_summary.json"
        with open(summary_path, "w") as f:
            json.dump(
                {
                    "scenarios": {
                        sid: {
                            "overall_score": r.get("overall_score"),
                            "critical_issues": r.get("critical_issues", []),
                            "items": {
                                k: {"passed": v.get("passed"), "score": v.get("score")}
                                for k, v in r.get("items", {}).items()
                            },
                        }
                        for sid, r in results.items()
                    }
                },
                f,
                ensure_ascii=False,
                indent=2,
            )
        print(f"Summary written to {summary_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
