"""Question plan management and repetition protection.

Split from pipeline.py — contains functions for managing question plans,
selecting candidates, detecting repetitive questions, and building
previously-asked sections.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass, field

from app.agents.chat.coverage_events import question_from_coverage_event
from app.agents.chat.coverage_events import canonical_coverage_phase
from app.agents.chat.coverage_config import get_coverage_thresholds
from app.agents.chat.decision_config import DecisionConfig
from app.agents.chat.state import ChatState

logger = logging.getLogger("interview-boss")

_MAX_CONSECUTIVE_SAME_QUESTION = 2
_MIN_MESSAGES_BEFORE_DEFAULT_BANK_QUESTION = 4
_MAX_LEDGER_CAT2_COUNT = 2
_BIG_TECH_PHASES = (
    "project_followup",
    "knowledge_probe",
    "algorithm_coding",
    "system_design",
    "behavioral",
)


@dataclass
class InterviewLedger:
    """Conversation-local ledger of asked question IDs and topic distribution."""

    asked_question_ids: set[int] = field(default_factory=set)
    asked_question_texts: set[str] = field(default_factory=set)
    cat1_counts: Counter[str] = field(default_factory=Counter)
    cat2_counts: Counter[str] = field(default_factory=Counter)
    question_type_counts: Counter[str] = field(default_factory=Counter)
    recent_topic_tokens: list[set[str]] = field(default_factory=list)

    def record_question(
        self, question: dict | None, question_type: str | None = None
    ) -> None:
        if not isinstance(question, dict):
            return
        raw_id = question.get("id")
        try:
            qid = int(raw_id)
        except (TypeError, ValueError):
            qid = 0
        if qid > 0:
            self.asked_question_ids.add(qid)

        question_text = str(question.get("question") or "")
        text_key = _normalize_question_text(question_text)
        if text_key:
            self.asked_question_texts.add(text_key)

        cat1 = str(question.get("cat1") or "").strip()
        cat2 = str(question.get("cat2") or "").strip()
        if cat1:
            self.cat1_counts[cat1] += 1
        if cat2:
            self.cat2_counts[cat2] += 1

        qtype = question_type or _infer_question_type(question)
        if qtype:
            self.question_type_counts[qtype] += 1

        tokens = _tokenize_for_overlap(
            " ".join([question_text, cat1, cat2, str(question.get("tags") or "")])
        )
        if tokens:
            self.recent_topic_tokens.append(tokens)
            self.recent_topic_tokens = self.recent_topic_tokens[-8:]


def _tokenize_for_overlap(text: str) -> set[str]:
    lowered = (text or "").lower()
    tokens = set(re.findall(r"[a-zA-Z][a-zA-Z0-9_+#.-]{1,}", lowered))
    tokens.update(re.findall(r"[一-鿿]{2,4}", lowered))
    return {t for t in tokens if len(t.strip()) >= 2}


def _normalize_question_text(text: str) -> str:
    return re.sub(
        r"[\s`'\"" "''。？?！!，,、：:；;（）()【】\\[\\]{}<>《》]", "", text or ""
    ).lower()


def _infer_question_type(question: dict | None) -> str:
    if not isinstance(question, dict):
        return ""
    text = " ".join(
        str(question.get(field) or "") for field in ("question", "cat1", "cat2", "tags")
    )
    normalized = text.lower()
    for phase in _BIG_TECH_PHASES:
        if phase in normalized:
            return phase
    if "system_design" in normalized or re.search(
        r"(系统设计|架构设计|高可用|扩展性|scalability)", text, re.I
    ):
        return "system_design"
    if "behavioral" in normalized or re.search(
        r"(行为面|协作|冲突|失败|复盘|STAR|影响力)", text, re.I
    ):
        return "behavioral"
    if re.search(
        r"(算法|代码|手撕|数据结构|链表|排序|二分|LRU|lru|滑动窗口)", text, re.I
    ):
        return "algorithm_coding"
    if re.search(r"(项目|架构|系统设计|Agent|RAG|LangGraph)", text, re.I):
        return "project_followup"
    if re.search(r"(Redis|MySQL|TCP|HTTP|缓存|锁|线程|进程|索引)", text, re.I):
        return "knowledge_probe"
    return "general"


def _canonical_interview_phase(question_type: str | None) -> str:
    qtype = (question_type or "").strip().lower()
    if qtype in {
        "project_followup",
        "knowledge_probe",
        "algorithm_coding",
        "system_design",
    }:
        return qtype
    if qtype in {"hr", "behavioral", "soft_skills", "hr_soft_skills"}:
        return "behavioral"
    return "other"


def _public_question_from_note(
    *,
    qid: int = 0,
    cat1: str = "",
    cat2: str = "",
    qtype: str = "",
    question: str = "",
) -> dict:
    return {
        "id": qid,
        "question": question,
        "cat1": cat1,
        "cat2": cat2,
        "tags": qtype,
    }


def _build_interview_ledger(state: ChatState) -> InterviewLedger:
    ledger = InterviewLedger()

    session_notes = state.get("session_notes", "") or ""
    for line in session_notes.splitlines():
        stripped = line.strip()
        if not stripped.startswith("[asked]"):
            continue
        body = stripped.replace("[asked]", "", 1).strip()
        match = re.match(
            r"(?P<cat1>[^/#:\[]+)?(?:/(?P<cat2>[^#:\[]+))?\s*"
            r"(?:#(?P<id>\d+))?\s*(?:\[(?P<type>[^\]]+)\])?\s*[:：]\s*(?P<question>.+)",
            body,
        )
        if match:
            data = match.groupdict()
            ledger.record_question(
                _public_question_from_note(
                    qid=int(data.get("id") or 0),
                    cat1=(data.get("cat1") or "").strip(),
                    cat2=(data.get("cat2") or "").strip(),
                    qtype=(data.get("type") or "").strip(),
                    question=(data.get("question") or "").strip(),
                ),
                question_type=(data.get("type") or "").strip() or None,
            )
        elif ":" in body or "：" in body:
            sep = ":" if ":" in body else "："
            cat, question = body.split(sep, 1)
            ledger.record_question(
                _public_question_from_note(cat1=cat.strip(), question=question.strip())
            )

    for msg in state.get("message_history", []) or []:
        if not isinstance(msg, dict) or msg.get("role") != "assistant":
            continue
        metadata = msg.get("metadata") or {}
        if isinstance(metadata, dict):
            coverage_events = metadata.get("coverage_events")
            recorded_coverage_event = False
            if isinstance(coverage_events, list):
                for event in coverage_events:
                    converted = question_from_coverage_event(event)
                    if converted:
                        question, phase = converted
                        ledger.record_question(question, question_type=phase)
                        recorded_coverage_event = True
            if recorded_coverage_event:
                continue

            selected = metadata.get("selected_question")
            if isinstance(selected, dict):
                ledger.record_question(selected)
            plan = metadata.get("question_plan")
            if isinstance(plan, dict):
                qid = plan.get("question_id")
                if qid:
                    try:
                        ledger.asked_question_ids.add(int(qid))
                    except (TypeError, ValueError):
                        pass
            for key in ("selected_basis_questions",):
                value = metadata.get(key)
                if isinstance(value, list):
                    for item in value:
                        if isinstance(item, dict):
                            ledger.record_question(item)

    return ledger


def _big_tech_phase_counts(ledger: InterviewLedger) -> Counter[str]:
    counts: Counter[str] = Counter()
    for question_type, count in ledger.question_type_counts.items():
        phase = _canonical_interview_phase(question_type)
        if phase in _BIG_TECH_PHASES:
            counts[phase] += count
    return counts


def _big_tech_next_focus(state: ChatState) -> dict:
    """Return runtime full-loop guidance derived from the asked-question ledger."""
    config = state.get("decision_config") or DecisionConfig()
    ledger = _build_interview_ledger(state)
    phase_counts = _big_tech_phase_counts(ledger)
    asked_count = sum(phase_counts.values())
    message_count = len(state.get("message_history", []) or [])
    thresholds = get_coverage_thresholds(
        str(state.get("job_position") or "agent_llm"),
        str(state.get("difficulty") or "mid"),
        state.get("rhythm_profile") or {},
    )
    coverage_complete = all(
        phase_counts.get(phase.value, 0) >= thresholds.get(phase, 0)
        for phase in thresholds
        if thresholds.get(phase, 0) > 0
    )

    distribution_plan = state.get("distribution_plan")
    if isinstance(distribution_plan, dict) and distribution_plan.get("soft_target_counts"):
        events = []
        for message in state.get("message_history", []) or []:
            if message.get("role") != "assistant":
                continue
            for event in (message.get("metadata") or {}).get("coverage_events", []) or []:
                if event.get("plan_id") == distribution_plan.get("plan_id"):
                    events.append(event)
        from app.agents.chat.distribution_controller import decide_next_question_type
        decision = decide_next_question_type(distribution_plan, events, {})
        if decision.preferred_type:
            return {
                "asked_count": len(events), "message_count": message_count,
                "phase_counts": {phase: phase_counts.get(phase, 0) for phase in _BIG_TECH_PHASES},
                "next_focus": {
                    "phase": decision.preferred_type,
                    "tool": "draw_questions" if decision.preferred_type in {"algorithm_coding", "system_design", "behavioral"} else "search_questions",
                    "question_type": decision.preferred_type,
                    "reason": "distribution_plan_target_deficit",
                },
            }

    # Opening phase: no tools, just greet and ask for self-introduction.
    if message_count < _MIN_MESSAGES_BEFORE_DEFAULT_BANK_QUESTION:
        focus = {
            "phase": "opening",
            "tool": "none",
            "question_type": "none",
            "reason": "开场阶段：邀请自我介绍或基于介绍自然追问，不要调用题库工具",
        }
    elif coverage_complete:
        focus = {
            "phase": "wrap_up",
            "tool": "none",
            "question_type": "wrap_up",
            "reason": "核心覆盖维度已达标，进入 HR/反问和收尾",
        }
    elif phase_counts["project_followup"] < config.min_project_followup:
        focus = {
            "phase": "project_followup",
            "tool": "search_questions",
            "question_type": "project_followup",
            "reason": "先确认候选人真实项目贡献和架构取舍",
        }
    elif phase_counts["knowledge_probe"] < config.min_knowledge_probe:
        focus = {
            "phase": "knowledge_probe",
            "tool": "search_questions",
            "question_type": "knowledge_probe",
            "reason": "从项目切到相关基础知识，验证不是只会背项目",
        }
    elif (
        asked_count >= config.algorithm_after_asked_count
        and phase_counts["algorithm_coding"] < config.min_algorithm_coding
    ):
        focus = {
            "phase": "algorithm_coding",
            "tool": "draw_questions",
            "question_type": "algorithm_coding",
            "reason": "大厂技术面通常需要至少一次 coding/算法信号",
        }
    elif (
        asked_count >= config.system_design_after_asked_count
        and phase_counts["system_design"] < config.min_system_design
    ):
        focus = {
            "phase": "system_design",
            "tool": "draw_questions",
            "question_type": "system_design",
            "reason": "补充系统设计/架构权衡信号",
        }
    elif (
        asked_count >= config.behavioral_after_asked_count
        or message_count >= config.behavioral_after_message_count
    ) and phase_counts["behavioral"] < config.min_behavioral:
        focus = {
            "phase": "behavioral",
            "tool": "draw_questions",
            "question_type": "hr",
            "reason": "补充协作、冲突、失败复盘和影响力信号",
        }
    else:
        focus = {
            "phase": "project_followup",
            "tool": "search_questions",
            "question_type": "project_followup",
            "reason": "继续围绕候选人经历做有依据的深挖",
        }

    return {
        "asked_count": asked_count,
        "message_count": message_count,
        "phase_counts": {
            phase: phase_counts.get(phase, 0) for phase in _BIG_TECH_PHASES
        },
        "next_focus": focus,
    }


def _build_big_tech_interview_harness_prompt(state: ChatState) -> str:
    guidance = _big_tech_next_focus(state)
    counts = guidance["phase_counts"]
    focus = guidance["next_focus"]
    coverage = ", ".join(f"{phase}={counts[phase]}" for phase in _BIG_TECH_PHASES)
    return (
        "<interview_harness>\n"
        "风格：中国互联网大厂技术面 + 大厂 full-loop 技术面。主要面向国内候选人，"
        "默认采用项目深挖、八股基础、场景题/系统设计、手撕代码、HR/稳定性、反问的穿插节奏。"
        "不要把面试做成连续抽题；每一轮都要服务于一个评估信号。\n"
        f"当前覆盖：{coverage}; asked_count={guidance['asked_count']}.\n"
        f"下一优先维度：{focus['phase']}，推荐工具：{focus['tool']}，"
        f"推荐 question_type：{focus['question_type']}，原因：{focus['reason']}。\n"
        "必须评估的信号：clarification（澄清问题）、problem solving、coding、testing、"
        "system_design、trade-off、behavioral、communication。\n"
        "国内 rhythm：先用自我介绍锚定简历亮点，再围绕一个项目连续深挖 2-3 层；"
        "随后切到相关八股基础或工程场景题，适时安排手撕代码；中后段补系统设计/线上故障/性能优化，"
        "最后覆盖 HR/稳定性并留出反问。"
        "同一维度不要连续超过 3 轮；候选人回答短时先澄清，回答完整后再进入下一评估维度。\n"
        "</interview_harness>"
    )


def _should_create_question_plan(state: ChatState) -> bool:
    """Return True when this turn is expected to ask a new bank-backed question."""
    if state.get("distribution_primary_required"):
        return True
    intent = state.get("intent")
    if intent == "practice_request":
        return True
    if intent == "interview_question" and _should_require_bank_question(state):
        return True
    if state.get("question_type") == "algorithm_coding":
        return True
    user_message = str(state.get("user_message") or "")
    return bool(re.search(r"(出题|来一道|换题|随机|手撕|代码题)", user_message))


def _should_require_bank_question(state: ChatState) -> bool:
    """Return True when the current turn should bind the next ask to the bank.

    The classifier writes ``requires_bank_question`` into state. This function
    trusts that field and only applies two hard overrides:
    - opening turns stay conversational (message_count below threshold)
    - incomplete/off-topic/repeated answers do not force a bank question
    """
    requires_bank = bool(state.get("requires_bank_question", False))
    if not requires_bank:
        return False

    # Hard overrides regardless of classifier suggestion.
    answer_quality = state.get("answer_quality", "complete")
    if answer_quality in ("incomplete", "off_topic", "repeated"):
        return False

    history = state.get("message_history")
    if history is None:
        return True
    message_count = len(history or [])
    if message_count < _MIN_MESSAGES_BEFORE_DEFAULT_BANK_QUESTION:
        return False
    return True


def _candidate_contains_negative_term(
    candidate: dict, negative_terms: list[str]
) -> bool:
    if not negative_terms:
        return False
    text = " ".join(
        str(candidate.get(field) or "")
        for field in ("question", "cat1", "cat2", "tags")
    ).lower()
    return any(str(term or "").lower() in text for term in negative_terms if term)


def _is_algorithm_candidate(candidate: dict) -> bool:
    text = " ".join(
        str(candidate.get(field) or "")
        for field in ("question", "cat1", "cat2", "tags")
    )
    return bool(
        re.search(r"(算法|代码|手撕|数据结构|链表|排序|二分|LRU|lru)", text, re.I)
    )


def _allowed_focus_from_question(question: dict) -> list[str]:
    focus: list[str] = []
    for field in ("cat2", "cat1", "tags"):
        value = str(question.get(field) or "").strip()
        if not value:
            continue
        for part in re.split(r"[,，、/\s]+", value):
            part = part.strip()
            if len(part) >= 2 and part not in focus:
                focus.append(part)
            if len(focus) >= 6:
                return focus
    for token in sorted(_tokenize_for_overlap(str(question.get("question") or "")))[:6]:
        if token not in focus:
            focus.append(token)
    return focus[:6]


def _select_question_for_plan(
    state: ChatState,
    candidates: list[dict],
) -> tuple[dict | None, str]:
    """Select one candidate for hard question-plan binding."""
    negative_terms = state.get("search_negative_terms", []) or []
    ledger = _build_interview_ledger(state)
    viable = [
        q
        for q in candidates
        if isinstance(q, dict)
        and q.get("id")
        and q.get("question")
        and not _candidate_contains_negative_term(q, negative_terms)
    ]
    if not viable:
        return None, "no_viable_candidate"

    required_type = (
        state.get("strategy_preferred_question_type") or state.get("question_type")
        if state.get("distribution_primary_required")
        else None
    )
    if required_type in _BIG_TECH_PHASES:
        compatible = [
            candidate
            for candidate in viable
            if canonical_coverage_phase(
                "",
                " ".join(
                    str(candidate.get(field) or "")
                    for field in ("question", "cat1", "cat2", "tags")
                ),
            )
            == required_type
        ]
        if not compatible:
            return None, "distribution_type_pool_exhausted"
        viable = compatible
        # The writer fallback must never substitute an incompatible candidate.
        state["candidate_questions"] = compatible
        state["retrieved_questions"] = compatible

    asked_ids, asked_texts = _previously_asked_question_keys(state)
    asked_ids = asked_ids | ledger.asked_question_ids
    asked_texts = asked_texts | ledger.asked_question_texts
    if asked_ids or asked_texts:
        unasked = [
            candidate
            for candidate in viable
            if not _candidate_was_previously_asked(candidate, asked_ids, asked_texts)
        ]
        if unasked:
            viable = unasked
            asked_filter_suffix = "_after_asked_filter"
        else:
            asked_filter_suffix = "_all_candidates_previously_asked"
    else:
        asked_filter_suffix = ""

    ledger_filtered = _filter_candidates_by_ledger(viable, ledger)
    if ledger_filtered and len(ledger_filtered) < len(viable):
        viable = ledger_filtered
        asked_filter_suffix = "_after_ledger_filter"

    if state.get("question_type") == "algorithm_coding":
        for candidate in viable:
            if _is_algorithm_candidate(candidate):
                return candidate, f"algorithm_candidate_match{asked_filter_suffix}"

    return viable[0], f"top_ranked_candidate{asked_filter_suffix}"


def _candidate_repeats_recent_topic(candidate: dict, ledger: InterviewLedger) -> bool:
    if not ledger.recent_topic_tokens:
        return False
    text = " ".join(
        str(candidate.get(field) or "")
        for field in ("question", "cat1", "cat2", "tags")
    )
    candidate_tokens = _tokenize_for_overlap(text)
    if not candidate_tokens:
        return False
    for previous in ledger.recent_topic_tokens[-3:]:
        if not previous:
            continue
        overlap = len(candidate_tokens & previous) / max(
            min(len(candidate_tokens), len(previous)), 1
        )
        if overlap >= 0.45:
            return True
    return False


def _filter_candidates_by_ledger(
    candidates: list[dict], ledger: InterviewLedger
) -> list[dict]:
    if not candidates:
        return candidates
    filtered = []
    for candidate in candidates:
        cat2 = str(candidate.get("cat2") or "").strip()
        if cat2 and ledger.cat2_counts.get(cat2, 0) >= _MAX_LEDGER_CAT2_COUNT:
            continue
        if _candidate_repeats_recent_topic(candidate, ledger):
            continue
        filtered.append(candidate)
    return filtered or candidates


def _previously_asked_question_keys(state: ChatState) -> tuple[set[int], set[str]]:
    ids: set[int] = set()
    texts: set[str] = set()

    def add_question(raw: object) -> None:
        if not isinstance(raw, dict):
            return
        raw_id = raw.get("id")
        try:
            qid = int(raw_id)
        except (TypeError, ValueError):
            qid = 0
        if qid > 0:
            ids.add(qid)
        text_key = _normalize_question_text(str(raw.get("question") or ""))
        if text_key:
            texts.add(text_key)

    for msg in state.get("message_history", []) or []:
        if not isinstance(msg, dict) or msg.get("role") != "assistant":
            continue
        metadata = msg.get("metadata") or {}
        if isinstance(metadata, dict):
            add_question(metadata.get("selected_question"))
            for key in (
                "selected_basis_questions",
                "candidate_questions",
                "retrieved_questions",
            ):
                value = metadata.get(key)
                if isinstance(value, list):
                    for item in value:
                        add_question(item)
        content = str(msg.get("content") or "")
        for pattern in (
            r"来写一道代码题[：:]\s*(.+?)(?:\n|$)",
            r"来聊一个八股[题：:]\s*(.+?)(?:\n|$)",
            r"我们先收束到一道具体题[：:]\s*(.+?)(?:\n|$)",
            r"我追问一个.+?问题[：:]\s*(.+?)(?:\n|$)",
            r"说说你对(.+?)的理解",
        ):
            for match in re.finditer(pattern, content):
                text_key = _normalize_question_text(match.group(1).strip())
                if text_key:
                    texts.add(text_key)

    return ids, texts


def _collect_question_exclusion_ids(state: ChatState) -> set[int]:
    """Collect question IDs that retrieval/draw tools should not return again.

    This is intentionally broader than ``InterviewLedger.asked_question_ids``:
    the ledger represents questions actually used for coverage, while this
    helper also includes candidates already exposed to the model/user in
    current or previous turns. Excluding exposed candidates at the tool boundary
    prevents the same candidate set from resurfacing in long interviews.
    """
    ids: set[int] = set(_build_interview_ledger(state).asked_question_ids)

    def add_question(raw: object) -> None:
        if not isinstance(raw, dict):
            return
        raw_id = raw.get("id")
        try:
            qid = int(raw_id)
        except (TypeError, ValueError):
            qid = 0
        if qid > 0:
            ids.add(qid)

    def add_items(raw_items: object) -> None:
        if not isinstance(raw_items, list):
            return
        for item in raw_items:
            add_question(item)

    add_question(state.get("selected_question"))
    add_items(state.get("candidate_questions"))
    add_items(state.get("retrieved_questions"))
    plan = state.get("next_question_plan")
    if isinstance(plan, dict):
        try:
            qid = int(plan.get("question_id") or 0)
        except (TypeError, ValueError):
            qid = 0
        if qid > 0:
            ids.add(qid)

    for msg in state.get("message_history", []) or []:
        if not isinstance(msg, dict) or msg.get("role") != "assistant":
            continue
        metadata = msg.get("metadata") or {}
        if not isinstance(metadata, dict):
            continue
        add_question(metadata.get("selected_question"))
        plan = metadata.get("question_plan")
        if isinstance(plan, dict):
            try:
                qid = int(plan.get("question_id") or 0)
            except (TypeError, ValueError):
                qid = 0
            if qid > 0:
                ids.add(qid)
        for key in (
            "selected_basis_questions",
            "candidate_questions",
            "retrieved_questions",
        ):
            add_items(metadata.get(key))

    return ids


def _candidate_was_previously_asked(
    candidate: dict,
    asked_ids: set[int],
    asked_texts: set[str],
) -> bool:
    try:
        qid = int(candidate.get("id"))
    except (TypeError, ValueError):
        qid = 0
    if qid > 0 and qid in asked_ids:
        return True
    text_key = _normalize_question_text(str(candidate.get("question") or ""))
    return bool(text_key and text_key in asked_texts)


def _maybe_create_question_plan(
    state: ChatState,
    *,
    force_candidate: dict | None = None,
) -> dict | None:
    """Create next_question_plan from current candidates when the turn needs a new question.

    When *force_candidate* is provided (agent explicit ``select_question`` call),
    use it directly instead of running the local heuristic.  Returns ``None`` and
    sets ``state["question_plan_reason"]`` to ``"negative_term_filtered"`` when the
    forced candidate matches a ``search_negative_terms`` entry.
    """
    if force_candidate is None and not _should_create_question_plan(state):
        return None

    negative_terms = state.get("search_negative_terms", []) or []

    if force_candidate is not None:
        # Agent explicitly selected this candidate — honour it unless filtered.
        if _candidate_contains_negative_term(force_candidate, negative_terms):
            state["question_plan_reason"] = "negative_term_filtered"
            return None
        selected = force_candidate
        selection_reason = "agent_explicit_selection"
    else:
        candidates = (
            state.get("candidate_questions") or state.get("retrieved_questions") or []
        )
        selected, selection_reason = _select_question_for_plan(state, candidates)

    if not selected:
        state["question_plan_reason"] = selection_reason
        return None

    plan = {
        "must_ask": True,
        "question_id": selected.get("id"),
        "question_text": str(selected.get("question") or ""),
        "basis_type": "drawn_question"
        if state.get("question_source") == "draw"
        else "interview_question",
        "source": state.get("question_source") or "search",
        "strategy": state.get("intent") or "new_question",
        "allowed_focus": _allowed_focus_from_question(selected),
        "forbidden_focus": negative_terms,
        "selection_reason": selection_reason,
    }
    state["selected_question"] = selected
    state["next_question_plan"] = plan
    state["selection_confidence"] = 1.0
    state["question_source_reason"] = "question_plan_bound"
    return plan


def _build_previously_asked_section(state: ChatState) -> str:
    """Build a section listing previously asked questions for the current turn.

    Extracts asked questions from session_notes (looked for [asked] entries)
    and message_history (question-like patterns). Returns a formatted string
    to be injected as a user message before the LLM call.
    """
    questions: list[str] = []

    # Extract from session_notes [asked] entries
    session_notes = state.get("session_notes", "")
    for match in re.finditer(r"\[asked\]\s*(.+)", session_notes):
        q = match.group(1).strip()
        if q:
            questions.append(q)

    # Extract from message_history assistant messages that look like question asks
    history = state.get("message_history", []) or []
    for msg in history:
        if msg.get("role") != "assistant":
            continue
        content = str(msg.get("content") or "")
        for pattern in (
            r"来写一道代码题[：:]\s*(.+?)(?:\n|$)",
            r"来聊一个八股[题：:]\s*(.+?)(?:\n|$)",
            r"我们先收束到一道具体题[：:]\s*(.+?)(?:\n|$)",
            r"说说你对(.+?)的理解",
        ):
            for m in re.finditer(pattern, content):
                q = m.group(1).strip()
                if q:
                    questions.append(q)

    # Deduplicate
    seen: set[str] = set()
    unique: list[str] = []
    for q in questions:
        key = q[:30]
        if key not in seen:
            seen.add(key)
            unique.append(q)

    if not unique:
        return ""

    lines = [f"{i}. {q}" for i, q in enumerate(unique, 1)]
    return (
        "[面试状态 - 由系统自动生成]\n"
        "## 本轮已问过的题目（禁止重复）\n"
        + "\n".join(lines)
        + "\n\n规则：不要再出以上题目或类似题目的变体。每次出题必须是新的知识点方向。"
    )


def _count_consecutive_similar_questions(state: ChatState) -> tuple[int, str]:
    """Count how many consecutive assistant messages are about the same core topic.

    Returns (count, topic_tokens_summary).  A "consecutive run" resets when
    the latest assistant message has significantly different core tokens from
    the previous one.

    Uses a lightweight token-overlap heuristic: extract Chinese spans/English
    words from each assistant message, compute overlap coefficient between
    consecutive pairs, and count the streak where overlap >= 0.15.
    """
    messages = state.get("message_history", []) or []
    assistant_msgs = [m for m in messages if m.get("role") == "assistant"]
    if len(assistant_msgs) < 2:
        return 0, ""

    def _core_tokens(text: str) -> set[str]:
        tokens = set()
        for t in re.findall(r"[a-zA-Z][a-zA-Z0-9_+#.-]{2,}", text.lower()):
            tokens.add(t)
        for t in re.findall(r"[一-鿿]{2,4}", text):
            tokens.add(t)
        # Remove generic filler tokens that inflate similarity
        _fillers = {
            "请",
            "问题",
            "回答",
            "面试",
            "一下",
            "具体",
            "详细",
            "介绍一下",
            "说说",
        }
        return tokens - _fillers

    recent_assistants = assistant_msgs[-6:]  # look at last 6 assistant messages
    token_sets = [_core_tokens(m.get("content", "")) for m in recent_assistants]

    # Walk backwards counting consecutive similar pairs
    # Use overlap coefficient: |A∩B| / min(|A|,|B|) — better than Jaccard
    # for detecting repetition when one message is much longer than the other.
    count = 0
    for i in range(len(token_sets) - 1, 0, -1):
        curr, prev = token_sets[i], token_sets[i - 1]
        if not curr or not prev:
            break
        intersection = curr & prev
        overlap = len(intersection) / max(min(len(curr), len(prev)), 1)
        if overlap >= 0.15:
            count += 1
        else:
            break

    # Return the topic summary of the most recent assistant message
    last_tokens = token_sets[-1] if token_sets else set()
    return count, "、".join(sorted(last_tokens)[:5])


def _count_consecutive_similar_user_answers(state: ChatState) -> int:
    """Count how many consecutive user messages are essentially the same answer.

    Uses the same token-overlap heuristic as _count_consecutive_similar_questions
    but on user messages, with a higher threshold (0.5) because candidate
    repetition is more clear-cut than interviewer topic similarity.

    Returns the number of consecutive similar pairs (0 = no repetition,
    1 = 2 similar in a row, 2 = 3 similar in a row, etc.).
    """
    messages = state.get("message_history", []) or []
    user_msgs = [m for m in messages if m.get("role") == "user"]
    if len(user_msgs) < 2:
        return 0

    def _core_tokens(text: str) -> set[str]:
        tokens = set()
        for t in re.findall(r"[a-zA-Z][a-zA-Z0-9_+#.-]{2,}", text.lower()):
            tokens.add(t)
        for t in re.findall(r"[一-鿿]{2,4}", text):
            tokens.add(t)
        _fillers = {
            "请",
            "问题",
            "回答",
            "面试",
            "一下",
            "具体",
            "详细",
            "介绍一下",
            "说说",
        }
        return tokens - _fillers

    recent = user_msgs[-6:]
    token_sets = [_core_tokens(m.get("content", "")) for m in recent]

    count = 0
    for i in range(len(token_sets) - 1, 0, -1):
        curr, prev = token_sets[i], token_sets[i - 1]
        if not curr or not prev:
            break
        intersection = curr & prev
        overlap = len(intersection) / max(min(len(curr), len(prev)), 1)
        if overlap >= 0.5:
            count += 1
        else:
            break
    return count


def _build_repetition_protection_note(state: ChatState) -> str:
    """Return a hard constraint note when repetition/topic escalation is high.

    Values are read from typed state fields (set in pipeline._step_classify)
    instead of being recomputed from message text.
    """
    user_repeat = state.get("repetition_streak", 0)
    if user_repeat >= 2:
        return (
            "## ⚠️ 候选人重复回答（硬约束）\n"
            f"候选人已连续 {user_repeat + 1} 次给出实质相同的回答。\n"
            "- 不要继续追问同一话题，这没有意义。\n"
            "- 直接指出候选人回答重复，然后切换到完全不同的面试方向。\n"
            "- 或者问候选人：'你有什么想问我们的吗？' 进入反问环节。\n"
        )

    escalation = state.get("escalation_level", 0)
    if escalation >= 3:
        return (
            "## ⚠️ 追问升级（硬约束）\n"
            "同一问题已连续追问多次且未能得到有效回答。\n"
            "- 不要再继续追问同一问题。\n"
            "- 切换到完全不同的面试方向。\n"
        )

    count, topic_summary = _count_consecutive_similar_questions(state)
    if count < _MAX_CONSECUTIVE_SAME_QUESTION:
        return ""

    logger.info(
        "ReAct trace: event=repetition_protection conversation_id=%s "
        "consecutive_count=%s topic=%s",
        state.get("conversation_id"),
        count,
        topic_summary,
    )

    return (
        "## ⚠️ 节奏保护（硬约束）\n"
        f"你已经连续 {count + 1} 次围绕同一话题「{topic_summary}」追问。\n"
        "- 不要再用同样的方式施压（如反复要求「写出来」「直接回答」）。\n"
        "- 必须做以下三选一：\n"
        "  1) 给一个简短提示/思路引导，让候选人自己想；\n"
        "  2) 记录为候选人的薄弱点，然后切换到下一个考察方向；\n"
        "  3) 降低难度，换个更基础的角度考察同一知识点。\n"
        "- 禁止原样重复上一题的施压话术。\n"
    )
