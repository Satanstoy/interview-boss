"""Interview E2E Target Adapter.

This adapter drives the same durable chat pipeline used by the product, while
keeping the candidate simulator and evaluation contract outside the target's
candidate-visible input. It is intentionally thin: orchestration belongs here;
quality scoring remains in ``evaluation.judge``.
"""

from __future__ import annotations

import os
import uuid
from typing import Any

from app.agents.chat.graph import run_chat
from app.services import chat_service
from app.services.llm import _call_llm_with_retry_messages


class InterviewE2EAdapter:
    """Run a benchmark case through the production interview pipeline."""

    async def prepare(
        self, case_snapshot: dict[str, Any], target_release: dict[str, Any]
    ) -> dict[str, Any]:
        candidate_view = dict(case_snapshot.get("candidate_view") or {})
        harness_context = dict(case_snapshot.get("harness_context") or {})
        contract = dict(case_snapshot.get("_eval_contract") or {})
        behavior_injections = {}
        for source_key in ("behavior_injections", "candidate_prompt_overrides"):
            for raw_turn, instruction in (harness_context.get(source_key) or {}).items():
                try:
                    behavior_injections[int(raw_turn)] = str(instruction)
                except (TypeError, ValueError):
                    continue
        return {
            "candidate_view": candidate_view,
            "harness_context": harness_context,
            "contract": contract,
            "target_release_key": target_release.get("release_key", ""),
            "seed": case_snapshot.get("_eval_seed"),
            "replication_index": case_snapshot.get("_eval_replication_index"),
            "behavior_injections": behavior_injections,
        }

    async def run(
        self, prepared_case: dict[str, Any], target_release: dict[str, Any]
    ) -> dict[str, Any]:
        candidate_view = prepared_case["candidate_view"]
        harness = prepared_case["harness_context"]
        max_turns = int(harness.get("max_turns") or candidate_view.get("max_turns") or 8)
        max_turns = max(1, min(max_turns, 50))
        user_id = int(
            target_release.get("created_by")
            or os.environ.get("EVAL_USER_ID", "1")
        )
        mode = str(candidate_view.get("mode") or "free_practice")
        conversation = chat_service.create_conversation(
            user_id=user_id,
            mode=mode,
            title=f"eval_{prepared_case.get('target_release_key', 'interview')}_{uuid.uuid4().hex[:8]}",
            resume_text=str(candidate_view.get("profile") or ""),
            difficulty=str(candidate_view.get("difficulty") or "mid"),
        )
        conversation_id = str(conversation["id"] if isinstance(conversation, dict) else conversation)
        candidate_messages = [
            {
                "role": "system",
                "content": (
                    "你是模拟面试中的候选人。只根据候选人画像回答面试官，"
                    "不要提及评测、rubric、硬断言或内部工具。\n"
                    f"候选人画像：{candidate_view.get('profile', '')}"
                ),
            }
        ]
        turns: list[dict[str, Any]] = []
        interviewer_response = ""
        errors: list[str] = []

        try:
            for turn_index in range(1, max_turns + 1):
                if turn_index == 1:
                    user_message = str(candidate_view.get("opening") or "你好，请开始面试。")
                else:
                    user_message = await self._candidate_reply(
                        interviewer_response,
                        candidate_messages,
                        target_release,
                        behavior_instruction=prepared_case["behavior_injections"].get(turn_index),
                        seed=prepared_case.get("seed"),
                    )
                result = await self._run_interviewer_turn(
                    conversation_id,
                    user_id,
                    user_message,
                    mode,
                    candidate_view,
                )
                interviewer_response = result["assistant"]
                if turn_index == 1:
                    candidate_messages.append({"role": "user", "content": interviewer_response})
                    candidate_messages.append({"role": "assistant", "content": user_message})
                turns.append(
                    {
                        "turn": turn_index,
                        "user": user_message,
                        "assistant": interviewer_response,
                        "events": result["events"],
                        "metadata": result.get("metadata", {}),
                    }
                )
                if result.get("terminal_error"):
                    errors.append(result["terminal_error"])
                if self._should_stop(interviewer_response, turns):
                    break
        except Exception as exc:
            errors.append(str(exc)[:500])

        return {
            "status": "succeeded" if turns and not errors else "failed",
            "conversation_id": conversation_id,
            "turns": turns,
            "errors": errors,
            "contract": prepared_case["contract"],
        }

    async def observe(self, raw_result: dict[str, Any]) -> dict[str, Any]:
        turns = raw_result.get("turns") or []
        errors = list(raw_result.get("errors") or [])
        contract = raw_result.get("contract") or {}
        all_events = [event for turn in turns for event in turn.get("events", [])]
        assistant_text = "\n".join(str(turn.get("assistant") or "") for turn in turns)
        hard_assertions = []
        for assertion in contract.get("hard_assertions") or []:
            assertion_id = assertion.get("id", "unknown") if isinstance(assertion, dict) else str(assertion)
            passed, evidence = self._check_assertion(assertion_id, turns, all_events, assistant_text, errors)
            hard_assertions.append({"id": assertion_id, "passed": passed, "evidence": evidence})
        return {
            "status": "succeeded" if raw_result.get("status") == "succeeded" else "failed",
            "payload": {
                "conversation_id": raw_result.get("conversation_id"),
                "turns": turns,
                "errors": errors,
            },
            "hard_assertions": hard_assertions,
            "contract_violations": [item["id"] for item in hard_assertions if not item["passed"]],
        }

    async def _candidate_reply(
        self,
        interviewer_message: str,
        messages: list[dict[str, str]],
        target_release: dict[str, Any],
        *,
        behavior_instruction: str | None = None,
        seed: int | None = None,
    ) -> str:
        if behavior_instruction:
            messages.append(
                {
                    "role": "system",
                    "content": f"[本轮候选人行为指令] {behavior_instruction}",
                }
            )
        if seed is not None:
            messages.append(
                {
                    "role": "system",
                    "content": f"本次评测 replication seed 为 {seed}，保持本次运行行为一致。",
                }
            )
        messages.append({"role": "user", "content": interviewer_message})
        manifest = target_release.get("candidate_simulator_manifest") or {}
        model = str(
            manifest.get("model")
            or os.environ.get("CANDIDATE_LLM_MODEL")
            or "candidate-simulator-model"
        )
        reply = await _call_llm_with_retry_messages(
            messages,
            model=model,
            temperature=float(manifest.get("temperature", 0.7)),
        )
        messages.append({"role": "assistant", "content": reply})
        return reply

    async def _run_interviewer_turn(
        self,
        conversation_id: str,
        user_id: int,
        user_message: str,
        mode: str,
        candidate_view: dict[str, Any],
    ) -> dict[str, Any]:
        request_id = uuid.uuid4().hex
        fingerprint = chat_service.build_turn_request_fingerprint(user_message)
        turn = chat_service.reserve_chat_turn(
            conversation_id,
            user_id,
            request_id,
            user_message,
            fingerprint,
        )
        events: list[dict[str, Any]] = []
        assistant_parts: list[str] = []
        metadata: dict[str, Any] = {}
        terminal_error = None
        try:
            async for event in run_chat(
                conversation_id=conversation_id,
                user_id=user_id,
                user_message=user_message,
                mode=mode,
                resume_text=str(candidate_view.get("profile") or ""),
                difficulty=str(candidate_view.get("difficulty") or "mid"),
                turn_id=turn.id,
                turn_fence=turn.fence,
            ):
                events.append(event)
                if event.get("type") == "chunk":
                    assistant_parts.append(str(event.get("content") or ""))
                elif event.get("type") == "done":
                    metadata = event.get("metadata") or {}
                elif event.get("type") == "error":
                    terminal_error = str(event.get("message") or "pipeline error")
            assistant = "".join(assistant_parts).strip()
            if terminal_error:
                chat_service.fail_chat_turn(turn.id, turn.fence, conversation_id, user_id, "EVAL_PIPELINE_ERROR")
            else:
                chat_service.finalize_chat_turn(
                    turn.id,
                    turn.fence,
                    conversation_id,
                    user_id,
                    assistant,
                    metadata,
                )
            return {"assistant": assistant, "events": events, "metadata": metadata, "terminal_error": terminal_error}
        except Exception:
            try:
                chat_service.fail_chat_turn(turn.id, turn.fence, conversation_id, user_id, "EVAL_PIPELINE_ERROR")
            except Exception:
                pass
            raise

    @staticmethod
    def _should_stop(response: str, turns: list[dict[str, Any]]) -> bool:
        if len(turns) < 2:
            return False
        signals = ("面试总结", "就到这里", "面试到这里结束", "有什么想问")
        return any(signal in response for signal in signals)

    @staticmethod
    def _check_assertion(
        assertion_id: str,
        turns: list[dict[str, Any]],
        events: list[dict[str, Any]],
        assistant_text: str,
        errors: list[str],
    ) -> tuple[bool, str]:
        if errors:
            return False, "; ".join(errors[:2])
        normalized = assertion_id.lower()
        if "selected_question" in normalized:
            passed = any(
                event.get("type") in {"tool_step", "retrieved"}
                or event.get("step") in {"select_question", "draw_questions", "search_questions"}
                for event in events
            )
            return passed, "observed question-selection event" if passed else "no question-selection event"
        if "tool_result_used" in normalized:
            tool_turns = [
                index for index, turn in enumerate(turns)
                if any(event.get("type") in {"tool_step", "retrieved"} for event in turn.get("events", []))
            ]
            passed = any(
                str(turn.get("assistant") or "").strip()
                for index, turn in enumerate(turns)
                if any(tool_index < index for tool_index in tool_turns)
            )
            return passed, "later question followed a tool event" if passed else "no later question after tool event"
        if "raw_tool_leak" in normalized:
            leak_markers = ("deterministic-interview-search", "search_questions", "raw tool", "tool payload")
            passed = not any(marker.lower() in assistant_text.lower() for marker in leak_markers)
            return passed, "no raw tool marker in assistant output" if passed else "raw tool marker leaked"
        if "correction" in normalized:
            correction_terms = {
                "bert": ("encoder", "判别式", "不是生成式"),
                "faiss": ("不支持事务", "不支持 acid", "不支持acid", "向量索引库"),
                "lru": ("least recently used", "最近最少使用"),
            }
            terms = next(
                (values for key, values in correction_terms.items() if key in normalized),
                (),
            )
            passed = any(term.lower() in assistant_text.lower() for term in terms)
            return passed, "correction appeared in visible output" if passed else "correction not found"
        if "closing" in normalized or "summary" in normalized:
            passed = any(
                token in assistant_text for token in ("面试总结", "就到这里", "有什么想问", "结束")
            ) or any(turn.get("metadata", {}).get("has_summary") for turn in turns)
            return passed, "observed closing evidence" if passed else "no closing evidence"
        return bool(turns), "completed at least one interview turn" if turns else "no interview turn"
