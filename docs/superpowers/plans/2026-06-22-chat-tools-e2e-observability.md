# Chat Tools E2E Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make real chat tools E2E observe selected_question and question_plan correctly through SSE.

**Architecture:** Keep the existing router metadata-splitting style. Add a new `question_plan` SSE event from `backend/app/routers/chat.py`, and update the manual verifier to parse both existing `selected_question` events and the new `question_plan` event.

**Tech Stack:** Python 3.10, FastAPI StreamingResponse SSE, existing backend script `verify_chat_tools_real_e2e.py`, Docker backend container.

---

## Task 1: Expose question_plan as an SSE event

**Files:**
- Modify: `backend/app/routers/chat.py`
- Test: `backend/tests/chat/test_react_e2e.py`

- [ ] **Step 1: Add failing test for question_plan event formatting**

Append this test to `backend/tests/chat/test_react_e2e.py`:

```python
def test_done_metadata_can_emit_question_plan_event():
    """Router-style metadata splitting should expose question_plan as its own SSE event."""
    from app.routers.chat import _metadata_events_from_done

    meta = {
        "selected_question": {"id": 7, "question": "RAG 检索怎么设计？", "cat1": "B", "cat2": "RAG"},
        "question_source": "search",
        "question_source_reason": "question_plan_bound",
        "question_plan": {
            "question_id": 7,
            "source": "search",
            "selection_reason": "top_ranked_candidate",
            "adherence": {"adheres": True, "score": 0.5, "reason": "keyword_overlap"},
            "repaired": False,
            "fallback_used": False,
        },
    }

    events = _metadata_events_from_done(meta)

    selected = next(event for event in events if event["type"] == "selected_question")
    assert selected["question"]["id"] == 7
    assert selected["reason"] == "question_plan_bound"

    plan = next(event for event in events if event["type"] == "question_plan")
    assert plan["question_id"] == 7
    assert plan["source"] == "search"
    assert plan["selection_reason"] == "top_ranked_candidate"
    assert plan["adherence"]["score"] == 0.5
    assert plan["repaired"] is False
    assert plan["fallback_used"] is False
```

- [ ] **Step 2: Run test to verify RED**

Run:

```bash
DEPLOY_MIN_FREE_MB=1024 ./deploy/docker-deploy.sh test -k test_done_metadata_can_emit_question_plan_event -q -o asyncio_mode=auto
```

Expected: FAIL because `_metadata_events_from_done` does not exist.

- [ ] **Step 3: Extract metadata event helper and add question_plan event**

In `backend/app/routers/chat.py`, add this helper above `send_message()`:

```python
def _metadata_events_from_done(meta: dict) -> list[dict]:
    """Split run_chat done metadata into public SSE events."""
    events: list[dict] = []
    if meta.get("candidate_questions"):
        events.append({"type": "candidates", "questions": meta.get("candidate_questions", [])})
    if "selected_question" in meta:
        events.append({
            "type": "selected_question",
            "question": meta.get("selected_question"),
            "source": meta.get("question_source", ""),
            "reason": meta.get("question_source_reason", ""),
        })
    if meta.get("question_plan"):
        events.append({"type": "question_plan", **meta.get("question_plan")})

    basis_type = meta.get("basis_type")
    if basis_type:
        events.append({
            "type": "basis",
            "basis_type": basis_type,
            "basis_question_ids": meta.get("basis_question_ids", []),
            "basis_confidence": meta.get("basis_confidence", 0.0),
            "should_show_references": meta.get("should_show_references", False),
            "selected_basis_questions": meta.get("selected_basis_questions", []),
            "resume_ref": meta.get("resume_ref", ""),
            "jd_ref": meta.get("jd_ref", ""),
        })
    if meta.get("resume_ref"):
        events.append({"type": "resume_ref", "name": meta["resume_ref"]})
    if meta.get("jd_ref"):
        events.append({"type": "jd_ref", "title": meta["jd_ref"]})
    return events
```

Then replace the metadata-yielding block in `event_stream()` with:

```python
                    for metadata_event in _metadata_events_from_done(meta):
                        yield f"data: {json.dumps(metadata_event, ensure_ascii=False)}\n\n"
```

Keep the final `done` event unchanged:

```python
                    yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"
```

- [ ] **Step 4: Run test to verify GREEN**

Run:

```bash
DEPLOY_MIN_FREE_MB=1024 ./deploy/docker-deploy.sh test -k test_done_metadata_can_emit_question_plan_event -q -o asyncio_mode=auto
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/chat.py backend/tests/chat/test_react_e2e.py
git commit -m "feat(backend): expose question plan sse event"
```

---

## Task 2: Parse selected_question and question_plan in real E2E verifier

**Files:**
- Modify: `backend/scripts/verify_chat_tools_real_e2e.py`

- [ ] **Step 1: Add script-level parser checks by running current verifier mentally via no test file**

No pytest file is needed for this manual script. The behavior to implement is:

```python
elif event_type == "selected_question":
    question = event.get("question")
    if isinstance(question, dict):
        result.selected_question_id = question.get("id")
        result.selected_question_text = str(question.get("question") or "")
elif event_type == "question_plan":
    result.question_plan_id = event.get("question_id")
    adherence = event.get("adherence") if isinstance(event.get("adherence"), dict) else {}
    score = adherence.get("score")
    if isinstance(score, (int, float)):
        result.adherence_score = float(score)
    result.repaired = bool(event.get("repaired", False))
    result.fallback_used = bool(event.get("fallback_used", False))
```

- [ ] **Step 2: Implement parser updates**

Update `_extract_case_result()` in `backend/scripts/verify_chat_tools_real_e2e.py` so it parses `selected_question` and `question_plan` events before falling back to metadata from `done`.

- [ ] **Step 3: Commit**

```bash
git add backend/scripts/verify_chat_tools_real_e2e.py
git commit -m "test(backend): parse chat tool sse metadata events"
```

---

## Task 3: Deploy and run real E2E

**Files:**
- No source changes expected.

- [ ] **Step 1: Deploy current backend**

Run:

```bash
DEPLOY_MIN_FREE_MB=1024 ./deploy/docker-deploy.sh update
```

Expected: backend and nginx rebuild, backend healthy.

- [ ] **Step 2: Run real E2E**

Run:

```bash
docker compose exec -e RUN_REAL_CHAT_E2E=1 backend uv run python backend/scripts/verify_chat_tools_real_e2e.py
```

Expected: report includes tool_call_rate, selected_question_rate, question_plan_rate, and no internal marker leaks.

- [ ] **Step 3: Record result in dev-log**

Append the observed result summary to `docs/dev-log/2026-06-22-chat-tools-real-e2e.md`.

- [ ] **Step 4: Commit dev-log if updated**

```bash
git add docs/dev-log/2026-06-22-chat-tools-real-e2e.md
git commit -m "docs: record chat tools real e2e result"
```

---

## Self-review checklist

- Router keeps existing candidates/selected/basis/resume/jd events.
- Router adds only one new public event: `question_plan`.
- Final `done` event remains unchanged.
- Verifier reads both router-split events and legacy `done.metadata` for compatibility.
- No passwords or API keys are required or printed.
