# Chat RAG Basis Optimization — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the reference mismatch where frontend shows raw search results instead of what the LLM actually used, optimize RAG retrieval quality, and integrate ONNX embedding model properly.

**Architecture:** Add `basis_type/basis_question_ids/basis_confidence/should_show_references` to ChatState. The generation prompt forces the LLM to output a structured JSON basis block at the end of its response. A parser extracts this basis and sends it via the `done` SSE event. Frontend displays basis instead of raw `retrieved_questions`. Separately, replace keyword extraction with structured query rewrite (retrieval_intent + main_topic + positive/negative terms) and add a heuristic reranker.

**Tech Stack:** Python 3.10 / FastAPI / SQLite / ONNX Runtime / FAISS / Vue 3 / Tailwind CSS

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `backend/app/agents/chat/state.py` | Modify | Add basis fields to ChatState |
| `backend/app/agents/chat/prompts.py` | Modify | Add BASIS_EXTRACT_GUIDANCE to generation prompts |
| `backend/app/agents/chat/nodes.py` | Modify | Add `_parse_basis_from_response()`, update `generate_response()` metadata |
| `backend/app/agents/chat/graph.py` | Modify | Initialize basis fields, yield basis in `done` event |
| `backend/app/routers/chat.py` | Modify | Forward basis fields in `done` SSE, persist to metadata |
| `backend/app/services/embedding_service.py` | Modify | Add `diagnose()` function, stricter prod fallback |
| `backend/app/services/memory_recall_service.py` | Modify | Replace keyword extraction with structured query rewrite |
| `backend/app/services/fts_service.py` | Modify | Add `_heuristic_rerank()` |
| `backend/scripts/backfill_embeddings.py` | Create | One-time backfill script for 324 questions |
| `backend/scripts/check_embedding_health.py` | Create | Diagnostic script |
| `backend/tests/chat/test_basis_parser.py` | Create | Tests for basis extraction |
| `backend/tests/chat/test_structured_rewrite.py` | Create | Tests for structured query rewrite |
| `backend/tests/chat/test_heuristic_rerank.py` | Create | Tests for heuristic reranker |
| `frontend/src/components/business/ChatMessage.vue` | Modify | Display basis_type + basis_question_ids |
| `frontend/src/components/business/ChatView.vue` | Modify | Capture basis SSE fields |

---

## Wave 1 — Foundation (No Dependencies, Parallelizable)

### Task 1.1: Embedding Diagnostic Script

**Files:**
- Create: `backend/scripts/check_embedding_health.py`
- Test: Inline (script is the test)

**Complexity:** Simple

- [ ] **Step 1: Create diagnostic script**

```python
"""Embedding health check — run via: docker compose exec backend uv run python backend/scripts/check_embedding_health.py"""
import os
import sys

def main():
    print("=== Embedding Health Check ===\n")

    # 1. Environment
    backend = os.environ.get("EMBEDDING_BACKEND", "auto")
    model_dir = os.environ.get("EMBEDDING_MODEL_DIR", "/app/models/bge-small-zh-v1.5")
    offline = os.environ.get("EMBEDDING_OFFLINE", "0")
    print(f"EMBEDDING_BACKEND={backend}")
    print(f"EMBEDDING_MODEL_DIR={model_dir}")
    print(f"EMBEDDING_OFFLINE={offline}")

    # 2. Model files
    from pathlib import Path
    p = Path(model_dir)
    onnx_path = p / os.environ.get("EMBEDDING_ONNX_FILE", "onnx/model_quantized.onnx")
    tok_path = p / "tokenizer.json"
    print(f"\nONNX exists: {onnx_path.exists()} ({onnx_path})")
    print(f"Tokenizer exists: {tok_path.exists()} ({tok_path})")

    # 3. Encode test
    print("\n--- Encode Test ---")
    try:
        from app.services.embedding_service import encode_texts
        import numpy as np
        vecs = encode_texts(["测试文本", "Redis 缓存穿透"])
        print(f"Shape: {vecs.shape}, dtype: {vecs.dtype}")
        print(f"Norm[0]: {np.linalg.norm(vecs[0]):.4f}")
        print(f"Backend used: {'ONNX' if vecs.shape[1] == 512 else 'hash'}")
    except Exception as e:
        print(f"ERROR: {e}")

    # 4. DB coverage
    print("\n--- Embedding Coverage ---")
    try:
        from app.db.connection import get_db_connection
        with get_db_connection() as conn:
            total = conn.execute("SELECT COUNT(*) FROM question_bank WHERE deleted_at IS NULL AND status='approved'").fetchone()[0]
            with_emb = conn.execute("SELECT COUNT(*) FROM question_bank WHERE deleted_at IS NULL AND status='approved' AND embedding IS NOT NULL").fetchone()[0]
            print(f"Approved questions: {total}")
            print(f"With embedding: {with_emb}")
            print(f"Coverage: {with_emb}/{total} ({100*with_emb/total:.0f}%)" if total else "N/A")
    except Exception as e:
        print(f"ERROR: {e}")

    print("\n=== Done ===")

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run and verify output**

Run: `docker compose exec backend uv run python backend/scripts/check_embedding_health.py`
Expected: Shows env vars, file existence, encode test output, DB coverage.

- [ ] **Step 3: Commit**

```bash
git add backend/scripts/check_embedding_health.py
git commit -m "feat(backend): add embedding diagnostic script"
```

---

### Task 1.2: Docker Compose — Embedding Model Volume + Env Vars

**Files:**
- Modify: `docker-compose.yml:26-33`
- Modify: `backend/.env.example`

**Complexity:** Simple

- [ ] **Step 1: Add embedding env vars to x-app-service**

In `docker-compose.yml`, add to the `environment` list under `x-app-service`:

```yaml
    - EMBEDDING_BACKEND=onnx
    - EMBEDDING_MODEL_DIR=/app/models/bge-small-zh-v1.5
    - EMBEDDING_OFFLINE=1
```

- [ ] **Step 2: Add model volume mount**

Add to the `volumes` list under `x-app-service`:

```yaml
    - /home/ubuntu/.cache/huggingface/hub/models--Xenova--bge-small-zh-v1.5:/app/models/bge-small-zh-v1.5:ro
```

Note: The exact source path depends on where the HF cache stores the model. Check with `ls /home/ubuntu/.cache/huggingface/hub/` to confirm. If the model hasn't been downloaded yet, run the backfill script first (Task 1.3) which will trigger download.

- [ ] **Step 3: Update .env.example**

Append to `backend/.env.example`:

```
# Embedding Model
EMBEDDING_BACKEND=onnx          # onnx | hash | auto
EMBEDDING_MODEL_DIR=/app/models/bge-small-zh-v1.5
EMBEDDING_OFFLINE=1             # 1 = never download in production
```

- [ ] **Step 4: Verify docker-compose syntax**

Run: `docker compose config --quiet`
Expected: No errors.

- [ ] **Step 5: Commit**

```bash
git add docker-compose.yml backend/.env.example
git commit -m "feat(deploy): add embedding model volume mount and env vars"
```

---

### Task 1.3: Stricter Production Embedding Fallback

**Files:**
- Modify: `backend/app/services/embedding_service.py:147-162`
- Test: `backend/tests/services/test_embedding_service.py`

**Complexity:** Simple

- [ ] **Step 1: Write failing test for prod fallback behavior**

```python
# backend/tests/services/test_embedding_service.py
import os
import pytest

def test_hash_fallback_raises_in_production(monkeypatch):
    """When EMBEDDING_BACKEND=onnx and model is missing, should raise (not silently fallback)"""
    monkeypatch.setenv("EMBEDDING_BACKEND", "onnx")
    monkeypatch.setenv("EMBEDDING_OFFLINE", "1")

    # Force re-read of env
    import importlib
    import app.services.embedding_service as mod
    mod._BACKEND = "onnx"
    mod._SESSION = None
    mod._TOKENIZER = None

    with pytest.raises(Exception):
        mod.encode_texts(["test"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec backend uv run pytest backend/tests/services/test_embedding_service.py -v`
Expected: FAIL (currently falls back silently)

- [ ] **Step 3: Implement stricter fallback**

In `embedding_service.py`, modify `encode_texts()`:

```python
def encode_texts(texts: List[str]) -> np.ndarray:
    """Encode texts as normalized float32 embeddings with shape ``(N, 512)``."""
    if not texts:
        return np.array([], dtype=np.float32).reshape(0, _DIMENSION)

    backend = _BACKEND
    if backend in {"onnx", "auto"}:
        try:
            return _encode_texts_onnx(texts)
        except Exception as exc:
            if backend == "onnx":
                # Strict: raise in production, never silently degrade
                raise
            # auto mode: log warning and fallback
            logger.warning("ONNX embedding unavailable, falling back to hash embeddings: %s", exc)
    if backend in {"hash", "auto"}:
        return _encode_texts_hash(texts)
    raise ValueError(f"Unsupported EMBEDDING_BACKEND={_BACKEND!r}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose exec backend uv run pytest backend/tests/services/test_embedding_service.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/embedding_service.py backend/tests/services/test_embedding_service.py
git commit -m "fix(backend): raise on ONNX failure in production instead of silent fallback"
```

---

## Wave 2 — Embedding Backfill (Depends on Wave 1)

### Task 2.1: Embedding Backfill Script

**Files:**
- Create: `backend/scripts/backfill_embeddings.py`

**Complexity:** Medium

- [ ] **Step 1: Create backfill script**

```python
"""Backfill embeddings for approved questions.

Usage:
  docker compose exec backend uv run python backend/scripts/backfill_embeddings.py [--dry-run] [--limit N]
"""
import argparse
import logging
import sys
import time

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("backfill")


def main():
    parser = argparse.ArgumentParser(description="Backfill question_bank embeddings")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    parser.add_argument("--limit", type=int, default=0, help="Max questions to process (0=all)")
    parser.add_argument("--batch-size", type=int, default=32, help="Encoding batch size")
    args = parser.parse_args()

    from app.db.connection import get_db_connection
    from app.services.embedding_service import encode_texts
    import numpy as np

    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT id, question FROM question_bank "
            "WHERE deleted_at IS NULL AND status = 'approved' AND embedding IS NULL "
            "ORDER BY id"
        ).fetchall()

    total = len(rows)
    if args.limit > 0:
        rows = rows[:args.limit]

    logger.info(f"Found {total} questions without embedding, processing {len(rows)}")
    if args.dry_run:
        logger.info("DRY RUN — no changes will be written")
        for r in rows[:5]:
            logger.info(f"  Would encode: id={r[0]}, q={r[1][:60]}...")
        if len(rows) > 5:
            logger.info(f"  ... and {len(rows)-5} more")
        return

    start = time.time()
    processed = 0
    errors = 0

    for i in range(0, len(rows), args.batch_size):
        batch = rows[i : i + args.batch_size]
        texts = [r[1] for r in batch]
        ids = [r[0] for r in batch]

        try:
            vecs = encode_texts(texts)
            with get_db_connection() as conn:
                for qid, vec in zip(ids, vecs):
                    blob = vec.astype(np.float32).tobytes()
                    conn.execute(
                        "UPDATE question_bank SET embedding = ? WHERE id = ?",
                        (blob, qid),
                    )
                conn.commit()
            processed += len(batch)
            elapsed = time.time() - start
            rate = processed / elapsed if elapsed > 0 else 0
            logger.info(f"Progress: {processed}/{len(rows)} ({rate:.1f} q/s)")
        except Exception as e:
            errors += len(batch)
            logger.error(f"Batch error at offset {i}: {e}")

    elapsed = time.time() - start
    logger.info(f"Done: {processed} encoded, {errors} errors, {elapsed:.1f}s total")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run dry-run to verify**

Run: `docker compose exec backend uv run python backend/scripts/backfill_embeddings.py --dry-run`
Expected: Shows "Found 324 questions without embedding" and preview of first 5.

- [ ] **Step 3: Run actual backfill (limited)**

Run: `docker compose exec backend uv run python backend/scripts/backfill_embeddings.py --limit 10`
Expected: Processes 10 questions, shows progress.

- [ ] **Step 4: Run full backfill**

Run: `docker compose exec backend uv run python backend/scripts/backfill_embeddings.py`
Expected: All 324 questions processed.

- [ ] **Step 5: Verify coverage**

Run: `docker compose exec backend uv run python backend/scripts/check_embedding_health.py`
Expected: Coverage: 324/324 (100%).

- [ ] **Step 6: Commit**

```bash
git add backend/scripts/backfill_embeddings.py
git commit -m "feat(backend): add embedding backfill script with dry-run and batch support"
```

---

## Wave 3 — Backend Basis + Structured Rewrite (Depends on Wave 2 for vector search, but can start in parallel)

### Task 3.1: Add Basis Fields to ChatState

**Files:**
- Modify: `backend/app/agents/chat/state.py:57-63`

**Complexity:** Simple

- [ ] **Step 1: Add basis fields to ChatState**

```python
    # === RAG 检索 ===
    keywords: list[str]  # LLM 提取的检索关键词
    search_query: Optional[str]  # 基于对话上下文改写的检索查询
    retrieved_questions: list[dict]  # FTS5 检索到的相关题目

    # === 生成依据（basis） ===
    basis_type: str  # 'question' | 'resume' | 'conversation' | 'mixed' | 'none'
    basis_question_ids: list[int]  # 实际引用的题目 ID 列表
    basis_confidence: float  # 0.0-1.0，LLM 对依据的置信度
    should_show_references: bool  # 是否在前端显示参考信息

    # === 输出 ===
    response: str  # AI 面试官回复
    metadata: dict  # 回复元数据（检索到的题目等）
```

- [ ] **Step 2: Initialize basis fields in graph.py**

In `graph.py` `run_chat()`, add to the state initialization (after line 117):

```python
        "basis_type": "none",
        "basis_question_ids": [],
        "basis_confidence": 0.0,
        "should_show_references": False,
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/agents/chat/state.py backend/app/agents/chat/graph.py
git commit -m "feat(backend): add basis fields to ChatState"
```

---

### Task 3.2: Add Basis Extraction Guidance to Prompts

**Files:**
- Modify: `backend/app/agents/chat/prompts.py:59-63` (JD prompt ending)
- Modify: `backend/app/agents/chat/prompts.py:120-124` (Practice prompt ending)

**Complexity:** Simple

- [ ] **Step 1: Add BASIS_EXTRACT_GUIDANCE constant**

Append to `prompts.py` (after MEMORY_EXTRACT_PROMPT):

```python
# ── 生成依据提取指引（注入到 system prompt 末尾）──
BASIS_EXTRACT_GUIDANCE = """
## 回复依据（必须在回答末尾输出）
在你的回答的最后一行，必须输出一个 JSON 块，格式如下：
```json
[BASIS]{{"type":"<type>","question_ids":[<ids>],"confidence":<0.0-1.0>,"show_refs":<true/false>}}[/BASIS]
```

字段说明:
- type: 你的回答的主要依据来源
  - "question" — 主要参考了题库中的面试题
  - "resume" — 主要参考了候选人的简历
  - "conversation" — 主要基于对话上下文（追问、澄清）
  - "mixed" — 同时参考了题目和其他材料
  - "none" — 纯自由发挥，没有参考任何材料
- question_ids: 你实际参考/引用的题目 ID 列表（从提供的题目信息中获取）。如果没有参考题目，用空数组 []
- confidence: 你对自己判断的置信度（0.0-1.0）
- show_refs: 是否应该在前端显示参考信息（true 如果参考了题目，false 如果是纯自由发挥）

规则:
- 如果你参考了提供的题目来提问或组织回答，type 必须是 "question" 或 "mixed"
- question_ids 只包含你实际使用的题目 ID，不要列出所有提供的题目
- 这个 JSON 块对用户不可见，用于系统记录
"""
```

- [ ] **Step 2: Inject into JD prompt**

In `INTERVIEW_SYSTEM_PROMPT_JD`, add `{basis_guidance}` placeholder before the closing `"""`:

Change the prompt ending from:
```
- 适当用 Markdown（代码块、列表）
"""
```
To:
```
- 适当用 Markdown（代码块、列表）

{basis_guidance}
"""
```

- [ ] **Step 3: Inject into Practice prompt**

Same change for `INTERVIEW_SYSTEM_PROMPT_PRACTICE`.

- [ ] **Step 4: Commit**

```bash
git add backend/app/agents/chat/prompts.py
git commit -m "feat(backend): add basis extraction guidance to generation prompts"
```

---

### Task 3.3: Basis Parser + Tests (TDD)

**Files:**
- Create: `backend/tests/chat/test_basis_parser.py`
- Modify: `backend/app/agents/chat/nodes.py` (add `_parse_basis_from_response()`)

**Complexity:** Medium

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/chat/test_basis_parser.py
import pytest
from app.agents.chat.nodes import _parse_basis_from_response


class TestParseBasisFromResponse:
    def test_parse_question_basis(self):
        response = "这是一段回答\n\n[BASIS]{\"type\":\"question\",\"question_ids\":[1,2,3],\"confidence\":0.9,\"show_refs\":true}[/BASIS]"
        result = _parse_basis_from_response(response, retrieved_ids=[1, 2, 3, 4, 5])
        assert result["basis_type"] == "question"
        assert result["basis_question_ids"] == [1, 2, 3]
        assert result["basis_confidence"] == 0.9
        assert result["should_show_references"] is True

    def test_parse_none_basis(self):
        response = "自由回答内容\n\n[BASIS]{\"type\":\"none\",\"question_ids\":[],\"confidence\":0.8,\"show_refs\":false}[/BASIS]"
        result = _parse_basis_from_response(response, retrieved_ids=[1, 2])
        assert result["basis_type"] == "none"
        assert result["basis_question_ids"] == []
        assert result["should_show_references"] is False

    def test_parse_mixed_basis(self):
        response = "回答\n\n[BASIS]{\"type\":\"mixed\",\"question_ids\":[10],\"confidence\":0.7,\"show_refs\":true}[/BASIS]"
        result = _parse_basis_from_response(response, retrieved_ids=[10, 20])
        assert result["basis_type"] == "mixed"
        assert result["basis_question_ids"] == [10]

    def test_no_basis_block_returns_defaults(self):
        response = "普通回答，没有 basis 块"
        result = _parse_basis_from_response(response, retrieved_ids=[1, 2])
        assert result["basis_type"] == "none"
        assert result["basis_question_ids"] == []
        assert result["should_show_references"] is False

    def test_invalid_json_returns_defaults(self):
        response = "回答\n\n[BASIS]{invalid json}[/BASIS]"
        result = _parse_basis_from_response(response, retrieved_ids=[1])
        assert result["basis_type"] == "none"

    def test_question_ids_clamped_to_retrieved(self):
        """Only allow IDs that were actually in retrieved_questions"""
        response = '回答\n\n[BASIS]{"type":"question","question_ids":[1,999],"confidence":0.9,"show_refs":true}[/BASIS]'
        result = _parse_basis_from_response(response, retrieved_ids=[1, 2, 3])
        assert result["basis_question_ids"] == [1]  # 999 filtered out

    def test_basis_block_stripped_from_response_text(self):
        response = "这是回答内容\n\n[BASIS]{\"type\":\"question\",\"question_ids\":[1],\"confidence\":0.9,\"show_refs\":true}[/BASIS]"
        result = _parse_basis_from_response(response, retrieved_ids=[1])
        assert "[BASIS]" not in result["clean_response"]
        assert "这是回答内容" in result["clean_response"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec backend uv run pytest backend/tests/chat/test_basis_parser.py -v`
Expected: FAIL (function doesn't exist yet)

- [ ] **Step 3: Implement `_parse_basis_from_response()`**

Add to `nodes.py` (after the existing helper functions, before node implementations):

```python
import re as _re
import json as _json


def _parse_basis_from_response(
    response: str, retrieved_ids: list[int] = None
) -> dict:
    """Extract basis JSON from LLM response and strip it from the text.

    Looks for: [BASIS]{"type":"...","question_ids":[...],"confidence":0.9,"show_refs":true}[/BASIS]

    Returns:
        dict with keys: basis_type, basis_question_ids, basis_confidence,
                        should_show_references, clean_response
    """
    defaults = {
        "basis_type": "none",
        "basis_question_ids": [],
        "basis_confidence": 0.0,
        "should_show_references": False,
        "clean_response": response,
    }

    if not response:
        return defaults

    # Extract basis block
    match = _re.search(r'\[BASIS\](\{.*?\})\[/BASIS\]', response, _re.DOTALL)
    if not match:
        return defaults

    raw_json = match.group(1)
    try:
        parsed = _json.loads(raw_json)
    except (_json.JSONDecodeError, TypeError):
        return defaults

    # Validate and extract fields
    basis_type = parsed.get("type", "none")
    valid_types = {"question", "resume", "conversation", "mixed", "none"}
    if basis_type not in valid_types:
        basis_type = "none"

    question_ids = parsed.get("question_ids", [])
    if not isinstance(question_ids, list):
        question_ids = []

    # Clamp to retrieved IDs
    retrieved_set = set(retrieved_ids or [])
    question_ids = [int(qid) for qid in question_ids if qid in retrieved_set]

    confidence = parsed.get("confidence", 0.0)
    if not isinstance(confidence, (int, float)):
        confidence = 0.0
    confidence = max(0.0, min(1.0, float(confidence)))

    show_refs = parsed.get("show_refs", False)
    if not isinstance(show_refs, bool):
        show_refs = False

    # Strip basis block from response text
    clean = _re.sub(r'\s*\[BASIS\]\{.*?\}\[/BASIS\]\s*$', '', response, flags=_re.DOTALL).rstrip()

    return {
        "basis_type": basis_type,
        "basis_question_ids": question_ids,
        "basis_confidence": confidence,
        "should_show_references": show_refs,
        "clean_response": clean,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec backend uv run pytest backend/tests/chat/test_basis_parser.py -v`
Expected: All 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/tests/chat/test_basis_parser.py backend/app/agents/chat/nodes.py
git commit -m "feat(backend): add basis parser with TDD tests"
```

---

### Task 3.4: Wire Basis into generate_response + Router + Metadata

**Files:**
- Modify: `backend/app/agents/chat/nodes.py:513-537` (metadata assembly in generate_response)
- Modify: `backend/app/routers/chat.py:244-258` (done event handling)

**Complexity:** Medium

- [ ] **Step 1: Update generate_response() metadata assembly**

In `nodes.py`, replace the metadata assembly block (lines 513-537) with:

```python
    # Extract basis from response
    retrieved_ids = [q["id"] for q in retrieved[:5]] if retrieved else []
    basis = _parse_basis_from_response(full_response, retrieved_ids)
    full_response = basis["clean_response"]

    # Build metadata
    metadata = {}
    metadata["basis_type"] = basis["basis_type"]
    metadata["basis_question_ids"] = basis["basis_question_ids"]
    metadata["basis_confidence"] = basis["basis_confidence"]
    metadata["should_show_references"] = basis["should_show_references"]

    # Legacy: include retrieved_questions for backward compat (old frontend)
    if retrieved:
        metadata["retrieved_questions"] = [
            {
                "id": q["id"],
                "question": q["question"],
                "cat1": q.get("cat1", ""),
                "company": _extract_company_from_sources(q),
                "round": _extract_round_from_sources(q),
            }
            for q in retrieved[:3]
        ]

    # Detect resume/JD references
    if resume_summary and _response_references_resume(full_response, resume_summary):
        metadata["resume_ref"] = _get_resume_name(user_id)
    if state.get("jd_text") and _response_references_jd(
        full_response, state.get("jd_text", "")
    ):
        metadata["jd_ref"] = _get_jd_title(state.get("jd_id"))

    yield {"type": "done", "metadata": metadata}
```

- [ ] **Step 2: Update router to forward basis fields**

In `routers/chat.py`, modify the `done` event handler (lines 244-258):

```python
                elif event_type == "done":
                    meta = event.get("metadata", {})
                    # Forward basis fields to frontend
                    basis_event = {
                        "type": "basis",
                        "basis_type": meta.get("basis_type", "none"),
                        "basis_question_ids": meta.get("basis_question_ids", []),
                        "basis_confidence": meta.get("basis_confidence", 0.0),
                        "should_show_references": meta.get("should_show_references", False),
                    }
                    yield f"data: {json.dumps(basis_event, ensure_ascii=False)}\n\n"
                    if meta.get("resume_ref"):
                        yield f"data: {json.dumps({'type': 'resume_ref', 'name': meta['resume_ref']}, ensure_ascii=False)}\n\n"
                    if meta.get("jd_ref"):
                        yield f"data: {json.dumps({'type': 'jd_ref', 'title': meta['jd_ref']}, ensure_ascii=False)}\n\n"
                    if full_response:
                        await run_db(
                            lambda: chat_service.save_message(
                                conversation_id,
                                "assistant",
                                full_response,
                                metadata=meta,
                            )
                        )
                    yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"
```

- [ ] **Step 3: Run backend tests**

Run: `docker compose exec backend uv run pytest backend/tests/chat/ -v`
Expected: All tests pass (including basis parser tests).

- [ ] **Step 4: Commit**

```bash
git add backend/app/agents/chat/nodes.py backend/app/routers/chat.py
git commit -m "feat(backend): wire basis extraction into generate_response and SSE router"
```

---

## Wave 4 — Frontend (Depends on Wave 3)

### Task 4.1: Update ChatView.vue to Capture Basis Event

**Files:**
- Modify: `frontend/src/components/business/ChatView.vue:570-640`

**Complexity:** Medium

- [ ] **Step 1: Add pending basis refs**

In `ChatView.vue`, add new refs alongside existing `pending*` refs:

```js
const pendingBasisType = ref(null)
const pendingBasisQuestionIds = ref([])
const pendingBasisConfidence = ref(0)
const pendingShouldShowReferences = ref(false)
```

- [ ] **Step 2: Handle `basis` SSE event**

In the event callback (around line 604), add:

```js
} else if (event.type === 'basis') {
  pendingBasisType.value = event.basis_type || 'none'
  pendingBasisQuestionIds.value = event.basis_question_ids || []
  pendingBasisConfidence.value = event.basis_confidence || 0
  pendingShouldShowReferences.value = event.should_show_references || false
}
```

- [ ] **Step 3: Attach basis to message metadata**

In the message assembly (around line 616), add:

```js
if (pendingBasisType.value && pendingBasisType.value !== 'none') {
  metadata.basis_type = pendingBasisType.value
  metadata.basis_question_ids = pendingBasisQuestionIds.value
  metadata.basis_confidence = pendingBasisConfidence.value
  metadata.should_show_references = pendingShouldShowReferences.value
}
```

- [ ] **Step 4: Reset pending basis refs after message**

Add to the reset block (around line 637):

```js
pendingBasisType.value = null
pendingBasisQuestionIds.value = []
pendingBasisConfidence.value = 0
pendingShouldShowReferences.value = false
```

- [ ] **Step 5: Frontend build check**

Run: `cd /home/ubuntu/sj/interview-boss/frontend && npm run build`
Expected: Build succeeds.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/business/ChatView.vue
git commit -m "feat(frontend): capture basis SSE event in ChatView"
```

---

### Task 4.2: Update ChatMessage.vue to Display Basis

**Files:**
- Modify: `frontend/src/components/business/ChatMessage.vue:58-107`

**Complexity:** Medium

- [ ] **Step 1: Update hasAnyReference computed**

```js
const hasAnyReference = computed(() => {
  const m = props.message.metadata
  // New: basis-based display
  if (m?.should_show_references && m?.basis_question_ids?.length) return true
  // Legacy: old messages with retrieved_questions
  if (m?.retrieved_questions?.length && !m?.basis_type) return true
  // Resume/JD refs
  return m?.resume_ref || m?.jd_ref
})
```

- [ ] **Step 2: Add basis question lookup**

Add a computed that resolves basis_question_ids to full question objects from retrieved_questions:

```js
const basisQuestions = computed(() => {
  const m = props.message.metadata
  if (!m?.basis_question_ids?.length || !m?.retrieved_questions?.length) return []
  return m.retrieved_questions.filter(q => m.basis_question_ids.includes(q.id))
})
```

- [ ] **Step 3: Update the citations template**

Replace the citations section (lines 58-107) with:

```html
      <!-- Citations: Sources -->
      <div v-if="hasAnyReference" class="mt-4 pt-4 border-t border-border/50">
        <!-- Basis questions (new format) -->
        <div v-if="basisQuestions.length" class="mb-3">
          <button
            @click="showRetrieved = !showRetrieved"
            class="flex items-center gap-2 text-xs text-muted-foreground hover:text-foreground transition-colors"
          >
            <BookOpen :size="14" class="text-primary" />
            <span class="font-medium">依据了 {{ basisQuestions.length }} 个题目</span>
            <ChevronDown :size="14" class="transition-transform" :class="showRetrieved ? 'rotate-180' : ''" />
          </button>

          <Transition name="expand">
            <div v-if="showRetrieved" class="mt-2 flex flex-col gap-2">
              <div
                v-for="q in basisQuestions"
                :key="q.id"
                class="flex items-start gap-3 p-3 rounded-lg bg-muted/30 border border-border/50 hover:bg-muted/50 transition-colors"
              >
                <div class="size-8 rounded-md bg-primary/10 flex items-center justify-center shrink-0">
                  <span class="text-xs font-bold text-primary">{{ q.cat1?.[0] || 'Q' }}</span>
                </div>
                <div class="flex-1 min-w-0">
                  <div class="text-sm text-foreground">{{ q.question }}</div>
                  <div class="flex items-center gap-2 mt-1 text-xs text-muted-foreground">
                    <span v-if="q.company" class="font-medium">{{ q.company }}</span>
                    <span v-if="q.round">{{ q.round }}</span>
                    <span v-if="q.cat1" class="text-primary">[{{ q.cat1 }}]</span>
                  </div>
                </div>
              </div>
            </div>
          </Transition>
        </div>

        <!-- Legacy: old retrieved_questions (no basis_type) -->
        <div v-else-if="message.metadata?.retrieved_questions?.length && !message.metadata?.basis_type" class="mb-3">
          <button
            @click="showRetrieved = !showRetrieved"
            class="flex items-center gap-2 text-xs text-muted-foreground hover:text-foreground transition-colors"
          >
            <BookOpen :size="14" class="text-primary" />
            <span class="font-medium">参考了 {{ message.metadata.retrieved_questions.length }} 个题目</span>
            <ChevronDown :size="14" class="transition-transform" :class="showRetrieved ? 'rotate-180' : ''" />
          </button>

          <Transition name="expand">
            <div v-if="showRetrieved" class="mt-2 flex flex-col gap-2">
              <div
                v-for="q in message.metadata.retrieved_questions"
                :key="q.id"
                class="flex items-start gap-3 p-3 rounded-lg bg-muted/30 border border-border/50 hover:bg-muted/50 transition-colors"
              >
                <div class="size-8 rounded-md bg-primary/10 flex items-center justify-center shrink-0">
                  <span class="text-xs font-bold text-primary">{{ q.cat1?.[0] || 'Q' }}</span>
                </div>
                <div class="flex-1 min-w-0">
                  <div class="text-sm text-foreground">{{ q.question }}</div>
                  <div class="flex items-center gap-2 mt-1 text-xs text-muted-foreground">
                    <span v-if="q.company" class="font-medium">{{ q.company }}</span>
                    <span v-if="q.round">{{ q.round }}</span>
                    <span v-if="q.cat1" class="text-primary">[{{ q.cat1 }}]</span>
                  </div>
                </div>
              </div>
            </div>
          </Transition>
        </div>

        <!-- Resume reference -->
        <div v-if="message.metadata?.resume_ref" class="flex items-center gap-2 text-xs text-muted-foreground mb-2">
          <FileText :size="14" class="text-amber-500 shrink-0" />
          <span>参考简历：</span>
          <span class="text-foreground font-medium truncate">{{ message.metadata.resume_ref }}</span>
        </div>

        <!-- JD reference -->
        <div v-if="message.metadata?.jd_ref" class="flex items-center gap-2 text-xs text-muted-foreground">
          <Briefcase :size="14" class="text-blue-500 shrink-0" />
          <span>参考 JD：</span>
          <span class="text-foreground font-medium truncate">{{ message.metadata.jd_ref }}</span>
        </div>
      </div>
```

- [ ] **Step 4: Frontend build check**

Run: `cd /home/ubuntu/sj/interview-boss/frontend && npm run build`
Expected: Build succeeds.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/business/ChatMessage.vue
git commit -m "feat(frontend): display basis questions instead of raw retrieved results"
```

---

## Wave 5 — RAG Quality (Depends on Wave 3, Parallel with Wave 4)

### Task 5.1: Structured Query Rewrite (TDD)

**Files:**
- Create: `backend/tests/chat/test_structured_rewrite.py`
- Modify: `backend/app/services/memory_recall_service.py`

**Complexity:** Complex

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/chat/test_structured_rewrite.py
import pytest
from app.services.memory_recall_service import (
    _parse_structured_rewrite,
    _build_search_params,
)


class TestParseStructuredRewrite:
    def test_valid_rewrite(self):
        raw = '{"retrieval_intent": "new_question", "main_topic": "Redis 缓存", "positive_terms": ["缓存穿透", "布隆过滤器"], "negative_terms": ["MySQL"]}'
        result = _parse_structured_rewrite(raw)
        assert result["retrieval_intent"] == "new_question"
        assert result["main_topic"] == "Redis 缓存"
        assert "缓存穿透" in result["positive_terms"]
        assert "MySQL" in result["negative_terms"]

    def test_invalid_json_returns_none(self):
        result = _parse_structured_rewrite("not json")
        assert result is None

    def test_missing_fields_returns_partial(self):
        raw = '{"retrieval_intent": "no_retrieval"}'
        result = _parse_structured_rewrite(raw)
        assert result["retrieval_intent"] == "no_retrieval"
        assert result["positive_terms"] == []


class TestBuildSearchParams:
    def test_new_question_builds_query(self):
        rewrite = {
            "retrieval_intent": "new_question",
            "main_topic": "Redis 缓存穿透",
            "positive_terms": ["布隆过滤器", "缓存雪崩"],
            "negative_terms": [],
        }
        params = _build_search_params(rewrite)
        assert "Redis" in " ".join(params["keywords"])
        assert params["search_query"] != ""
        assert params["answer_complete"] is True

    def test_no_retrieval_returns_empty(self):
        rewrite = {
            "retrieval_intent": "no_retrieval",
            "main_topic": "",
            "positive_terms": [],
            "negative_terms": [],
        }
        params = _build_search_params(rewrite)
        assert params["keywords"] == []
        assert params["search_query"] == ""

    def test_followup_uses_conversation_context(self):
        rewrite = {
            "retrieval_intent": "project_followup",
            "main_topic": "项目架构",
            "positive_terms": ["微服务"],
            "negative_terms": [],
        }
        params = _build_search_params(rewrite)
        assert params["answer_complete"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec backend uv run pytest backend/tests/chat/test_structured_rewrite.py -v`
Expected: FAIL

- [ ] **Step 3: Implement structured rewrite in memory_recall_service.py**

Add the new prompt and parsing functions:

```python
# ── Structured Query Rewrite Prompt (replaces keyword extraction) ──
STRUCTURED_REWRITE_PROMPT = """分析面试对话上下文，生成结构化检索参数。

## 任务
根据面试官的问题和候选人的回答，生成用于题库检索的结构化参数。

## 用户消息
{user_message}

## 最近对话
{recent_context}

## 输出格式（严格 JSON）
{{
  "retrieval_intent": "<intent>",
  "main_topic": "<核心话题，10字以内>",
  "positive_terms": ["<要检索的关键词>", ...],
  "negative_terms": ["<要排除的主题>", ...]
}}

## retrieval_intent 取值
- new_question: 面试官要出新题（回答完整或换题请求）
- project_followup: 面试官在追问项目细节
- knowledge_probe: 面试官在探测某个知识点的深度
- no_retrieval: 闲聊/打招呼/不需要检索

## 规则
- positive_terms 必须是 2-4 字的技术术语
- 从面试官的问题中提取话题，不是从用户回答中提取
- negative_terms 用于排除不相关方向（可为空）
- main_topic 简短精准"""


def _parse_structured_rewrite(raw: str) -> dict | None:
    """Parse structured rewrite JSON from LLM response."""
    defaults = {
        "retrieval_intent": "new_question",
        "main_topic": "",
        "positive_terms": [],
        "negative_terms": [],
    }
    try:
        parsed = _json.loads(raw)
        if not isinstance(parsed, dict):
            return None
        result = {**defaults}
        for key in defaults:
            if key in parsed:
                result[key] = parsed[key]
        # Validate retrieval_intent
        valid_intents = {"new_question", "project_followup", "knowledge_probe", "no_retrieval"}
        if result["retrieval_intent"] not in valid_intents:
            result["retrieval_intent"] = "new_question"
        # Ensure lists
        for list_key in ("positive_terms", "negative_terms"):
            if not isinstance(result[list_key], list):
                result[list_key] = []
        return result
    except (_json.JSONDecodeError, TypeError):
        return None


def _build_search_params(rewrite: dict) -> dict:
    """Convert structured rewrite into search parameters."""
    intent = rewrite.get("retrieval_intent", "new_question")

    if intent == "no_retrieval":
        return {
            "keywords": [],
            "search_query": "",
            "answer_complete": False,
        }

    positive = rewrite.get("positive_terms", [])
    main_topic = rewrite.get("main_topic", "")

    # Build keywords: positive_terms + main_topic tokens
    keywords = list(positive)
    if main_topic:
        # Add main topic words if not already in keywords
        topic_words = _re.findall(r'[一-鿿]{2,4}|[a-zA-Z][a-zA-Z0-9]+', main_topic)
        for w in topic_words:
            if w not in keywords:
                keywords.append(w)

    keywords = keywords[:6]
    search_query = " ".join(keywords) if keywords else ""

    # Determine answer_complete based on intent
    answer_complete = intent == "new_question"

    return {
        "keywords": keywords,
        "search_query": search_query,
        "answer_complete": answer_complete,
    }
```

- [ ] **Step 4: Integrate into classify_and_recall()**

In `classify_and_recall()`, after the LLM call that returns `intent, memory_ids, keywords, search_query, answer_complete`, add a structured rewrite call. Specifically, modify the LLM prompt to also include the structured rewrite task, or add a second LLM call.

The cleanest approach: Add the structured rewrite as an additional field in the existing `INTENT_AND_MEMORY_PROMPT` JSON output.

Update `INTENT_AND_MEMORY_PROMPT` to add:
```
## 任务5: 结构化检索改写
分析面试官的问题，生成结构化检索参数。
{structured_rewrite_format}
```

And update the expected JSON output:
```
{{"intent": "...", "relevant_memory_ids": [...], "keywords": [...], "search_query": "...", "answer_complete": true/false, "rewrite": {{"retrieval_intent": "...", "main_topic": "...", "positive_terms": [...], "negative_terms": [...]}}}}
```

Then in the parsing code, extract `rewrite` and use `_build_search_params()` to override keywords/search_query/answer_complete.

- [ ] **Step 5: Run tests to verify they pass**

Run: `docker compose exec backend uv run pytest backend/tests/chat/test_structured_rewrite.py -v`
Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/tests/chat/test_structured_rewrite.py backend/app/services/memory_recall_service.py
git commit -m "feat(backend): replace keyword extraction with structured query rewrite"
```

---

### Task 5.2: Heuristic Reranker (TDD)

**Files:**
- Create: `backend/tests/chat/test_heuristic_rerank.py`
- Modify: `backend/app/services/fts_service.py`

**Complexity:** Medium

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/chat/test_heuristic_rerank.py
import pytest
from app.services.fts_service import _heuristic_rerank


class TestHeuristicRerank:
    def test_keyword_overlap_boosts_score(self):
        results = [
            {"id": 1, "question": "Redis 缓存穿透怎么解决", "cat1": "八股文", "cat2": "Redis"},
            {"id": 2, "question": "MySQL 索引优化", "cat1": "八股文", "cat2": "MySQL"},
        ]
        reranked = _heuristic_rerank(results, keywords=["Redis", "缓存"], intent="new_question")
        assert reranked[0]["id"] == 1  # Redis question should be first

    def test_intent_alignment(self):
        results = [
            {"id": 1, "question": "项目架构设计", "cat1": "项目复盘", "cat2": "架构"},
            {"id": 2, "question": "Redis 缓存穿透", "cat1": "八股文", "cat2": "Redis"},
        ]
        reranked = _heuristic_rerank(results, keywords=["架构"], intent="project_followup")
        assert reranked[0]["id"] == 1  # Project question for project_followup

    def test_empty_results_returns_empty(self):
        assert _heuristic_rerank([], keywords=["test"]) == []

    def test_no_keywords_returns_original_order(self):
        results = [{"id": 1, "question": "A"}, {"id": 2, "question": "B"}]
        reranked = _heuristic_rerank(results, keywords=[])
        assert reranked[0]["id"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec backend uv run pytest backend/tests/chat/test_heuristic_rerank.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `_heuristic_rerank()`**

Add to `fts_service.py` (after `_mmr_diversify`):

```python
def _heuristic_rerank(
    results: list[dict],
    keywords: list[str] = None,
    intent: str = "new_question",
) -> list[dict]:
    """Lightweight heuristic reranker based on keyword overlap, position matching, and intent alignment.

    Scoring:
    - Keyword overlap: +10 per keyword match in question, +5 in tags/cat1/cat2
    - Intent alignment: boost matching categories
    - Position: slight bonus for earlier results (stability)
    """
    if not results or not keywords:
        return results

    # Intent → preferred cat1 mapping
    intent_cat1_map = {
        "new_question": None,  # No preference
        "project_followup": "项目复盘",
        "knowledge_probe": None,
    }
    preferred_cat1 = intent_cat1_map.get(intent)

    scored = []
    for i, r in enumerate(results):
        score = 0.0
        q_lower = (r.get("question", "") or "").lower()
        tags_lower = (r.get("tags", "") or "").lower()
        cat1 = r.get("cat1", "") or ""
        cat2 = r.get("cat2", "") or ""

        for kw in keywords:
            kw_lower = kw.lower()
            if kw_lower in q_lower:
                score += 10
            if kw_lower in tags_lower:
                score += 5
            if kw_lower in cat1.lower() or kw_lower in cat2.lower():
                score += 3

        # Intent alignment
        if preferred_cat1 and cat1 == preferred_cat1:
            score += 8

        # Stability: slight bonus for earlier positions
        score += max(0, 5 - i)

        scored.append((score, i, r))

    scored.sort(key=lambda x: (-x[0], x[1]))
    return [item[2] for item in scored]
```

- [ ] **Step 4: Integrate into hybrid_search()**

In `hybrid_search()`, add after MMR diversify (before the final return):

```python
    # ── 优化 4: Heuristic rerank ──
    if keywords:
        fused = _heuristic_rerank(fused, keywords=original_keywords or keywords, intent="new_question")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `docker compose exec backend uv run pytest backend/tests/chat/test_heuristic_rerank.py -v`
Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/tests/chat/test_heuristic_rerank.py backend/app/services/fts_service.py
git commit -m "feat(backend): add heuristic reranker with keyword overlap and intent alignment"
```

---

## Wave 6 — Verification + Polish (Depends on all previous waves)

### Task 6.1: Full Integration Verification

**Files:** None (verification only)

**Complexity:** Simple

- [ ] **Step 1: Run full backend test suite**

Run: `docker compose exec backend uv run pytest backend/tests/ -q`
Expected: All tests pass.

- [ ] **Step 2: Run frontend build**

Run: `cd /home/ubuntu/sj/interview-boss/frontend && npm run build`
Expected: Build succeeds.

- [ ] **Step 3: Run embedding diagnostic**

Run: `docker compose exec backend uv run python backend/scripts/check_embedding_health.py`
Expected: Coverage 100%, ONNX backend active.

- [ ] **Step 4: Manual smoke test**

Start the app, create a new conversation, send a message, verify:
- `basis` SSE event arrives in browser DevTools Network tab
- ChatMessage shows "依据了 N 个题目" (not "参考了")
- Old messages still show "参考了 N 个题目"

---

## Parallel Task Graph

```
Wave 1 (parallel):
  ├── Task 1.1: Embedding diagnostic script
  ├── Task 1.2: Docker compose env vars + volume
  └── Task 1.3: Stricter production fallback (TDD)

Wave 2 (depends on Wave 1):
  └── Task 2.1: Backfill script

Wave 3 (depends on Wave 2 for vector, can start in parallel for non-vector parts):
  ├── Task 3.1: Add basis fields to ChatState
  ├── Task 3.2: Add basis extraction guidance to prompts
  └── Task 3.3: Basis parser (TDD)

Wave 4 (depends on Wave 3):
  └── Task 3.4: Wire basis into generate_response + router

Wave 5 (depends on Wave 3, parallel with Wave 4):
  ├── Task 4.1: ChatView.vue basis event capture
  └── Task 4.2: ChatMessage.vue basis display

Wave 6 (depends on Wave 3, parallel with Waves 4-5):
  ├── Task 5.1: Structured query rewrite (TDD)
  └── Task 5.2: Heuristic reranker (TDD)

Wave 7 (depends on all):
  └── Task 6.1: Full integration verification
```

**Maximum parallelism:** 3 tasks in Wave 1, 2 tasks in Wave 5/6.

---

## Atomic Commit Strategy

| Commit | Files | Message |
|--------|-------|---------|
| 1 | `scripts/check_embedding_health.py` | `feat(backend): add embedding diagnostic script` |
| 2 | `docker-compose.yml`, `.env.example` | `feat(deploy): add embedding model volume mount and env vars` |
| 3 | `embedding_service.py`, test | `fix(backend): raise on ONNX failure in production instead of silent fallback` |
| 4 | `scripts/backfill_embeddings.py` | `feat(backend): add embedding backfill script with dry-run and batch support` |
| 5 | `state.py`, `graph.py` | `feat(backend): add basis fields to ChatState` |
| 6 | `prompts.py` | `feat(backend): add basis extraction guidance to generation prompts` |
| 7 | `nodes.py`, test | `feat(backend): add basis parser with TDD tests` |
| 8 | `nodes.py`, `chat.py` router | `feat(backend): wire basis extraction into generate_response and SSE router` |
| 9 | `ChatView.vue` | `feat(frontend): capture basis SSE event in ChatView` |
| 10 | `ChatMessage.vue` | `feat(frontend): display basis questions instead of raw retrieved results` |
| 11 | `memory_recall_service.py`, test | `feat(backend): replace keyword extraction with structured query rewrite` |
| 12 | `fts_service.py`, test | `feat(backend): add heuristic reranker with keyword overlap and intent alignment` |

---

## Verification Criteria Summary

| Task | Verification Command | Expected Result |
|------|---------------------|-----------------|
| 1.1 | `python scripts/check_embedding_health.py` | Shows env, files, encode test, coverage |
| 1.2 | `docker compose config --quiet` | No errors |
| 1.3 | `pytest backend/tests/services/test_embedding_service.py -v` | PASS |
| 2.1 | `python scripts/backfill_embeddings.py --dry-run` | Shows 324 questions to process |
| 3.1 | Code review | State fields present, initialized in graph.py |
| 3.2 | Code review | BASIS_EXTRACT_GUIDANCE in both prompts |
| 3.3 | `pytest backend/tests/chat/test_basis_parser.py -v` | 7/7 PASS |
| 3.4 | `pytest backend/tests/chat/ -v` | All PASS |
| 4.1 | `cd frontend && npm run build` | Build succeeds |
| 4.2 | `cd frontend && npm run build` | Build succeeds |
| 5.1 | `pytest backend/tests/chat/test_structured_rewrite.py -v` | All PASS |
| 5.2 | `pytest backend/tests/chat/test_heuristic_rerank.py -v` | All PASS |
| 6.1 | `pytest backend/tests/ -q && cd frontend && npm run build` | All PASS + build succeeds |

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| LLM doesn't output [BASIS] block | Parser returns defaults (basis_type=none), old behavior preserved |
| Basis JSON malformed | Parser catches JSONDecodeError, returns defaults |
| question_ids not in retrieved set | Parser clamps to retrieved_ids, no hallucinated IDs |
| Old messages break | Frontend checks `basis_type` existence; falls back to legacy `retrieved_questions` display |
| Embedding model not in Docker image | Diagnostic script (Task 1.1) catches this immediately |
| Backfill fails mid-way | Script is idempotent (only processes WHERE embedding IS NULL), can re-run |
