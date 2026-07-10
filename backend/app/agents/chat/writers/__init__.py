"""Contract Writers — 将 TurnContract 表达为自然用户可见文本。

每个 writer 只负责把 contract 表达出来，不拥有流程决策。
"""

from app.agents.chat.writers.closing_writer import generate_closing_utterance

__all__ = ["generate_closing_utterance"]
