"""InterviewBoss eval framework package."""

from .types import (
    CandidateLLMConfig,
    JudgeLLMConfig,
    Scenario,
    DEFAULT_BASE_URL,
    DEFAULT_OUTPUT_DIR,
    SUMMARY_SIGNALS,
    CORRECTION_OUTPUT_SIGNALS,
    MID_LEVEL_PERSONA,
    SENIOR_PERSONA,
    _check_ratio,
    _check_error_corrected,
    _candidate_asks_to_end,
    _interviewer_forces_close,
)
from .rubrics import (
    LONG_SESSION_SCORING,
    ERROR_CORRECTION_SCORING,
    EARLY_CLOSE_SCORING,
    PROPER_END_SCORING,
    INSUFFICIENT_EVIDENCE_SCORING,
    COUNTER_QUESTION_SCORING,
    GREETING_SCORING,
    TOOL_TIMING_SCORING,
    NATURAL_CLOSING_SCORING,
    COUNTER_QUESTION_FLOW_SCORING,
)
from .scenarios import SCENARIOS
from .candidate import SmartCandidateAgent, _resolve_candidate_config, _resolve_judge_config
from .http_client import (
    _call_openai_compatible_chat,
    _json_request,
    _login,
    _ensure_internal_e2e_token,
    _resolve_token,
    _parse_sse_event,
    _iter_sse_events,
    _assistant_text_from_events,
)
from .metrics import (
    extract_metrics,
    _event_data,
    _event_tool_name,
    _ids_from_object,
    _candidate_ids_for_turn,
    find_cross_turn_duplicates,
    query_asked_questions_db,
    _detect_early_close_refused,
    _detect_counter_question_answered,
    _count_tools_by_turn,
    _detect_meta_remarks,
    _detect_self_intro_invite,
    _count_tools_on_counter_turn,
)
from .scoring import (
    score_scenario,
    llm_score_scenario,
    _build_conversation_transcript,
    _build_scoring_criteria_text,
    _event_tools_for_turn,
    _preview,
)
from .reports import (
    llm_generate_report,
    write_reports,
    write_unified_report,
    _render_markdown_report,
)
from .runner import (
    create_conversation,
    _delete_conversation,
    send_message_and_collect,
    run_evaluation,
    _build_parser,
    main,
)

__all__ = [
    "CandidateLLMConfig",
    "JudgeLLMConfig",
    "Scenario",
    "SCENARIOS",
    "SmartCandidateAgent",
    "extract_metrics",
    "score_scenario",
    "llm_score_scenario",
    "run_evaluation",
    "write_reports",
    "write_unified_report",
    "main",
]
