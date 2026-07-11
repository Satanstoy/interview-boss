"""Contract Writers — 将 TurnContract 表达为自然用户可见文本。

每个 writer 只负责把 contract 表达出来，不拥有流程决策。
"""

from app.agents.chat.writers.closing_writer import generate_closing_utterance
from app.agents.chat.writers.clarify_writer import generate_clarification
from app.agents.chat.writers.counter_writer import generate_counter_answer
from app.agents.chat.writers.followup_writer import generate_followup
from app.agents.chat.writers.question_writer import generate_question_with_validation
from app.agents.chat.writers.summary_writer import generate_structured_summary

__all__ = [
    "generate_clarification",
    "generate_closing_utterance",
    "generate_counter_answer",
    "generate_followup",
    "generate_question_with_validation",
    "generate_structured_summary",
]
