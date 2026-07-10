"""Evaluation runner: orchestrates conversation, scoring, and reporting."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from .types import Scenario, CandidateLLMConfig, JudgeLLMConfig, DEFAULT_OUTPUT_DIR
from .http_client import (
    _json_request,
    _resolve_token,
    _iter_sse_events,
    _assistant_text_from_events,
)
from .candidate import SmartCandidateAgent, _resolve_candidate_config, _resolve_judge_config
from .metrics import extract_metrics
from .scoring import score_scenario, llm_score_scenario
from .reports import llm_generate_report, write_reports, write_unified_report
from .scenarios import SCENARIOS


def create_conversation(
    base_url: str,
    token: str,
    scenario: Scenario,
) -> tuple[str, str | None]:
    """Create a conversation and return (conversation_id, opening_message)."""
    body: dict[str, Any] = {
        "mode": scenario.mode,
        "title": f"eval_{scenario.scenario_id}_{int(time.time())}",
    }
    if scenario.extra_args:
        body.update(scenario.extra_args)
    if scenario.persona.get("resume_text"):
        body["resume_text"] = scenario.persona["resume_text"]

    response = _json_request("POST", f"{base_url}/api/chat/conversations", body=body, token=token)
    conv_id = response.get("id") or response.get("conversation_id") or response.get("data", {}).get("id")
    if not conv_id:
        raise RuntimeError(f"Failed to create conversation: {response}")
    opening = response.get("data", {}).get("opening_message") or response.get("opening_message")
    return str(conv_id), opening


def _delete_conversation(base_url: str, token: str, conversation_id: str) -> None:
    try:
        _json_request("DELETE", f"{base_url}/api/chat/conversations/{conversation_id}", token=token)
    except Exception:
        pass


def send_message_and_collect(
    base_url: str,
    token: str,
    conversation_id: str,
    message: str,
    model: str | None = None,
    timeout: int = 120,
) -> dict[str, Any]:
    """Send a message and collect the response."""
    start = time.monotonic()
    events = _iter_sse_events(base_url, token, conversation_id, message, model=model, timeout=timeout)
    elapsed = time.monotonic() - start
    assistant = _assistant_text_from_events(events)
    return {
        "assistant": assistant,
        "events": events,
        "latency_sec": round(elapsed, 2),
    }


def run_evaluation(
    scenario: Scenario,
    args: argparse.Namespace,
    auth_token: str,
    candidate_config: CandidateLLMConfig,
    judge_config: JudgeLLMConfig | None,
) -> dict[str, Any]:
    """Run a full evaluation for a single scenario."""
    conversation_id, opening = create_conversation(args.base_url, auth_token, scenario)
    candidate = SmartCandidateAgent(scenario.persona, scenario.active_skills, candidate_config)
    turns: list[dict[str, Any]] = []
    interviewer_response = opening or "你好，我们开始今天的模拟面试，请先做一个简单自我介绍。"

    try:
        for turn_idx in range(1, scenario.max_turns + 1):
            # Inject turn-level candidate behavior override if configured
            if scenario.candidate_prompt_overrides and turn_idx in scenario.candidate_prompt_overrides:
                override = scenario.candidate_prompt_overrides[turn_idx]
                candidate.inject_turn_instruction(override)

            if turn_idx == 1:
                user_msg = scenario.persona["opening"]
            else:
                user_msg = candidate.respond(interviewer_response)

            try:
                result = send_message_and_collect(
                    args.base_url,
                    auth_token,
                    conversation_id,
                    user_msg,
                    args.interviewer_model,
                    timeout=args.turn_timeout,
                )
                interviewer_response = result["assistant"]
                events = result["events"]
                latency_sec = result["latency_sec"]
            except Exception as exc:
                events = [{"type": "error", "message": str(exc)}]
                latency_sec = 0
                interviewer_response = ""

            turn = {
                "turn": turn_idx,
                "user": user_msg,
                "assistant": interviewer_response,
                "events": events,
                "latency_sec": latency_sec,
            }
            turns.append(turn)
            if scenario.early_exit_check and scenario.early_exit_check(turns):
                break

        metrics = extract_metrics(turns, conversation_id)
        if judge_config:
            scores = llm_score_scenario(scenario, turns, metrics, judge_config)
        else:
            scores = score_scenario(scenario, metrics)
        return {
            "scenario_id": scenario.scenario_id,
            "conversation_id": conversation_id,
            "turns": turns,
            "metrics": metrics,
            "scores": scores,
        }
    finally:
        if args.keep_conversation:
            print(f"Conversation kept: {conversation_id}")
        else:
            try:
                _delete_conversation(args.base_url, auth_token, conversation_id)
            except Exception as exc:
                print(f"Warning: failed to delete conversation: {exc}", file=sys.stderr)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="InterviewBoss Agent Eval Framework")
    parser.add_argument("--scenario", action="append", help="Scenario ID to run")
    parser.add_argument("--base-url", default=os.getenv("EVAL_BASE_URL", "http://localhost"))
    parser.add_argument("--username", default=os.getenv("EVAL_USERNAME", "sj"))
    parser.add_argument("--password", default=os.getenv("EVAL_PASSWORD", ""))
    parser.add_argument("--token", default=os.getenv("EVAL_TOKEN", ""))
    parser.add_argument("--interviewer-model", default=None)
    parser.add_argument("--candidate-api-key", default=None)
    parser.add_argument("--candidate-base-url", default=None)
    parser.add_argument("--candidate-model", default=None)
    parser.add_argument("--candidate-timeout", default=None)
    parser.add_argument("--judge-api-key", default=None)
    parser.add_argument("--judge-base-url", default=None)
    parser.add_argument("--judge-model", default=None)
    parser.add_argument("--judge-timeout", default=None)
    parser.add_argument("--no-llm-judge", action="store_true")
    parser.add_argument("--turn-timeout", type=int, default=120)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--keep-conversation", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    if not os.getenv("RUN_REAL_INTERVIEW_EVAL"):
        print("Set RUN_REAL_INTERVIEW_EVAL=1 to run real evals.", file=sys.stderr)
        return 1

    parser = _build_parser()
    args = parser.parse_args(argv)

    scenario_ids = args.scenario or list(SCENARIOS.keys())
    for sid in scenario_ids:
        if sid not in SCENARIOS:
            print(f"Unknown scenario: {sid}. Available: {', '.join(SCENARIOS.keys())}", file=sys.stderr)
            return 1

    try:
        candidate_config = _resolve_candidate_config(args)
    except RuntimeError as exc:
        print(f"Interview eval failed: {exc}", file=sys.stderr)
        return 1

    judge_config = _resolve_judge_config(args)
    if judge_config:
        print(f"LLM Judge enabled: model={judge_config.model}, base_url={judge_config.base_url}")
    else:
        print("LLM Judge disabled: using rule-based scoring.")

    all_results: list[dict[str, Any]] = []
    all_passed = True

    try:
        for scenario_id in scenario_ids:
            scenario = SCENARIOS[scenario_id]
            print(f"Running scenario: {scenario_id}")
            auth_token = _resolve_token(args)
            result = run_evaluation(scenario, args, auth_token, candidate_config, judge_config)

            llm_report = None
            if judge_config:
                print(f"  Generating LLM report for {scenario_id}...")
                llm_report = llm_generate_report(result, judge_config)

            json_path, md_path = write_reports(result, args.output_dir, llm_report=llm_report)
            if args.verbose:
                print(json.dumps(result["scores"], ensure_ascii=False, indent=2))
            print(f"- JSON: {json_path}")
            print(f"- MD: {md_path}")
            all_passed = all_passed and bool(result["scores"]["passed"])
            all_results.append(result)

        if len(all_results) > 1:
            unified_path = write_unified_report(all_results, args.output_dir, judge_config)
            print(f"\n统一报告: {unified_path}")
        return 0 if all_passed else 1
    except Exception as exc:
        print(f"Interview eval failed: {exc}", file=sys.stderr)
        return 1
