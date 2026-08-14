"""对话业务逻辑 — 会话管理、消息存储、记忆管理"""

import uuid
import json
import logging
import sqlite3
import hashlib
from dataclasses import dataclass
from typing import Optional
from app.db.connection import get_db_connection
from app.agents.chat.coverage_config import get_coverage_thresholds
from app.agents.chat.rhythm_profile import build_rhythm_profile
from app.agents.chat.agent_profile import is_agent_development_position

logger = logging.getLogger("interview-boss")


from app.services.chat_common import (
    ConversationNotFound,
    ConversationNotWritable,
    TurnInProgress,
    TurnCancelled,
    TurnNotFound,
    TurnIdempotencyConflict,
    TurnUserMessageConflict,
    SideEffectConflict,
    SIDE_EFFECT_MAX_ATTEMPTS,
    ChatTurn,
    _chat_turn_from_row,
    build_turn_request_fingerprint,
    _safe_json_loads,
    FLUSH_UTILIZATION_THRESHOLD,
)


from app.services.chat_turn_service import (
    get_chat_turn,
    reserve_chat_turn,
    reserve_chat_revision,
    cancel_chat_turn,
    assert_chat_turn_active,
    finalize_chat_turn,
    fail_chat_turn,
    generate_opening_message,
)

from app.services.chat_conversation_service import (
    create_conversation,
    get_conversations,
    get_conversation,
    update_conversation_title,
    archive_conversation,
    delete_conversation,
    update_conversation_metadata,
    get_conversation_metadata,
    get_conversation_metadata_snapshot,
)
from app.services.chat_message_service import (
    save_user_message_if_writable,
    save_assistant_message_if_active,
    save_message,
    get_messages,
    get_distribution_events,
    get_recent_messages,
    get_message_count,
    get_conversation_question_ids,
)

from app.services.chat_memory_service import (
    save_memory,
    get_memories,
    deactivate_memory,
    get_memory_summaries,
    get_memories_by_ids,
    get_topic_memories,
    get_resume_memory,
    save_resume_memory,
)
from app.services.chat_session_service import (
    get_session_notes,
    get_session_notes_snapshot,
    update_session_notes,
    flush_needed,
    flush_session_to_memories,
    search_past_sessions,
    format_session_recall,
)
from app.services.chat_durable_service import (
    _side_effect_job_dict,
    get_side_effect_job,
    claim_side_effect_job,
    complete_side_effect_job,
    fail_side_effect_job,
    commit_memory_extraction_job,
    create_candidate_set,
    get_candidate_set,
    consume_candidate_set,
    resolve_candidate_question,
    append_interview_event,
    get_interview_events,
    fold_interview_events,
    record_assistant_generation,
    get_current_assistant_generation,
)
