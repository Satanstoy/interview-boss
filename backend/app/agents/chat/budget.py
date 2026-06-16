"""Token Budget Manager — 统一上下文预算追踪 + 五级渐进式压缩级联

设计哲学（来自 Claude Code）:
- "Defer as long as possible, keep it as cheap as possible, escalate in stages"
- 预留输出和恢复空间
- 零 LLM 成本路径优先
"""
import logging
from dataclasses import dataclass
from typing import Optional

from app.agents.chat.nodes import (
    _count_chars,
    _snip_messages,
    _truncate_to_budget,
)
from app.services.llm import _call_llm_with_retry
from app.agents.chat.prompts import (
    CONTEXT_COMPRESS_PROMPT,
    CONTEXT_COMPRESS_UPDATE_PROMPT,
)

logger = logging.getLogger("interview-boss")


@dataclass
class BudgetSnapshot:
    """上下文预算快照，用于监控和调试"""
    system_chars: int = 0
    compressed_chars: int = 0
    memory_chars: int = 0
    retrieved_chars: int = 0
    recent_chars: int = 0
    current_msg_chars: int = 0
    total_chars: int = 0
    available_chars: int = 0
    utilization_pct: float = 0.0
    compression_tier: str = "none"


class TokenBudgetManager:
    """统一上下文预算管理器 + 五级渐进式压缩级联

    级联顺序（成本递增）:
    1. 缩减 recent window (5→3→2 轮) — 零 LLM 成本
    2. Snip 旧消息 — 零 LLM 成本
    3. Session notes 替代 — 零 LLM 成本
    4. Micro-compact (notes + truncated snip) — 零 LLM 成本
    5. LLM 结构化压缩 — 最后手段
    """

    def __init__(
        self,
        total_budget_chars: int = 28000,
        output_reserve_chars: int = 4000,
        system_overhead_chars: int = 500,
    ):
        self.total_budget = total_budget_chars
        self.output_reserve = output_reserve_chars
        self.system_overhead = system_overhead_chars
        # 各 section 预算（字符数）
        self.system_budget = 3000  # 与 nodes.py SYSTEM_BUDGET 一致
        self.memory_budget = 800
        self.compressed_budget = 1200
        self.retrieved_budget = 1000

    def _available_for_context(self, recent_chars: int = 0) -> int:
        """计算可用于 compressed context 的空间"""
        used = (
            self.system_budget
            + self.memory_budget
            + self.retrieved_budget
            + self.system_overhead
            + recent_chars
        )
        available = self.total_budget - self.output_reserve - used
        return max(available, 200)  # 至少保留 200 字符

    def measure(self, state: dict) -> BudgetSnapshot:
        """测量当前上下文各 section 的消耗"""
        messages = state.get("message_history", [])
        compressed = state.get("compressed_context")
        memory_summaries = state.get("memory_summaries", [])
        retrieved = state.get("retrieved_questions", [])
        user_message = state.get("user_message", "")

        system_chars = min(self.system_budget, 2000)
        compressed_chars = len(compressed) if compressed else 0
        memory_chars = sum(len(m.get("summary", "")) for m in memory_summaries)
        retrieved_chars = sum(len(q.get("question", "")) for q in retrieved)
        recent_chars = _count_chars(messages[-10:]) if messages else 0
        current_msg_chars = len(user_message)

        total = (
            system_chars + compressed_chars + memory_chars
            + retrieved_chars + recent_chars + current_msg_chars
            + self.system_overhead
        )
        available = self.total_budget - self.output_reserve
        utilization = (total / available * 100) if available > 0 else 100.0

        return BudgetSnapshot(
            system_chars=system_chars,
            compressed_chars=compressed_chars,
            memory_chars=memory_chars,
            retrieved_chars=retrieved_chars,
            recent_chars=recent_chars,
            current_msg_chars=current_msg_chars,
            total_chars=total,
            available_chars=available,
            utilization_pct=round(utilization, 1),
        )

    def needs_compression(self, snapshot: BudgetSnapshot) -> bool:
        """判断是否需要压缩"""
        return snapshot.total_chars > snapshot.available_chars

    async def compress(
        self,
        messages: list[dict],
        session_notes: str,
        existing_compressed: Optional[str],
        user_id: Optional[int] = None,
    ) -> tuple[list[dict], Optional[str], str]:
        """五级渐进式压缩级联

        OpenClaw 设计哲学：flush before discard — 压缩前先持久化重要记忆。

        Returns:
            (recent_messages, compressed_context, tier_used)
        """
        if not messages:
            return [], None, "none"

        total = _count_chars(messages)
        # 使用全量消息判断是否需要压缩（measure 只看最近 10 条）
        full_snapshot = self.measure({
            "message_history": messages,
            "compressed_context": existing_compressed,
            "session_notes": session_notes,
            "memory_summaries": [],
            "retrieved_questions": [],
            "user_message": "",
        })
        # 重新计算 total_chars 使用全量消息
        full_snapshot.total_chars = (
            full_snapshot.system_chars + full_snapshot.compressed_chars
            + full_snapshot.memory_chars + full_snapshot.retrieved_chars
            + total + full_snapshot.current_msg_chars + self.system_overhead
        )
        if not self.needs_compression(full_snapshot):
            recent = messages[-10:] if messages else []
            return recent, existing_compressed, "none"

        # Pre-compaction flush（OpenClaw: flush before discard）
        # 在压缩丢弃信息前，先将 session notes 中的重要记忆持久化
        if user_id and session_notes:
            from app.services.chat_service import flush_needed, flush_session_to_memories
            if flush_needed(session_notes, full_snapshot.utilization_pct):
                flushed = flush_session_to_memories(user_id, session_notes)
                if flushed > 0:
                    logger.info(f"Pre-compaction flush: 持久化 {flushed} 条记忆")

        # 尝试不同 keep_rounds（5→3→2）逐级缩减
        for keep_rounds in [5, 3, 2]:
            keep_count = keep_rounds * 2
            if keep_count >= len(messages):
                # 消息不够拆分，直接返回
                return messages, existing_compressed, "none"

            old_messages = messages[:-keep_count]
            recent = messages[-keep_count:]
            recent_chars = _count_chars(recent)
            available = self._available_for_context(recent_chars)

            # Cascade 2: Snip 旧消息（零 LLM 成本）
            snipped = _snip_messages(old_messages)
            combined = self._combine(existing_compressed, snipped)
            if len(combined) <= available:
                return recent, combined, "snip"

            # Cascade 3: Session notes 替代（零 LLM 成本）
            if session_notes:
                notes_combined = self._combine(existing_compressed, session_notes)
                if len(notes_combined) <= available:
                    return recent, notes_combined, "session_notes"

            # Cascade 4: Micro-compact (notes + truncated snip)（零 LLM 成本）
            if session_notes:
                micro = f"{session_notes}\n\n[早期对话摘要]\n{snipped}"
                if len(micro) > available:
                    micro = _truncate_to_budget(micro, available)
                return recent, micro, "micro_compact"

            # 如果 snip 就够了（即使没有 notes），直接返回
            if len(snipped) <= available:
                return recent, combined, "snip"

        # Cascade 5: LLM 结构化压缩（最后手段）
        keep_count = 2 * 2
        old_messages = messages[:-keep_count]
        recent = messages[-keep_count:]
        recent_chars = _count_chars(recent)
        available = self._available_for_context(recent_chars)

        llm_compressed = await self._llm_compress(
            old_messages, existing_compressed=existing_compressed, state_user_id=user_id
        )
        combined = self._combine(existing_compressed, llm_compressed)
        if len(combined) > available:
            combined = _truncate_to_budget(combined, available)

        return recent, combined, "llm"

    def _combine(self, existing: Optional[str], new_part: str) -> str:
        """合并已有压缩上下文和新部分"""
        if existing:
            return f"{existing}\n\n---\n\n{new_part}"
        return new_part

    async def _llm_compress(
        self,
        old_messages: list[dict],
        existing_compressed: Optional[str] = None,
        state_user_id: int = None,
    ) -> str:
        """LLM 结构化压缩（最后手段），支持迭代更新模式"""
        history_text = "\n".join(
            f"{'面试官' if m['role'] == 'assistant' else '候选人'}: {m['content'][:200]}"
            for m in old_messages
        )
        try:
            if existing_compressed:
                prompt = CONTEXT_COMPRESS_UPDATE_PROMPT.format(
                    existing_summary=existing_compressed,
                    message_history=history_text,
                )
            else:
                prompt = CONTEXT_COMPRESS_PROMPT.format(message_history=history_text)

            result = await _call_llm_with_retry(
                prompt,
                user_id=state_user_id,
            )
            summary = result.strip()
            if not summary:
                logger.warning("LLM 结构化压缩返回空结果，回退到模板截断")
                return _snip_messages(old_messages)
            return summary
        except Exception as e:
            logger.warning(f"LLM 结构化压缩失败，回退到模板截断: {e}")
            return _snip_messages(old_messages)
