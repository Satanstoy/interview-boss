from scripts.eval_framework import http_client, runner


def test_eval_request_body_carries_client_request_id():
    body = http_client.build_message_request_body(
        "回答一下缓存击穿",
        model="test-model",
        client_request_id="req-123",
    )

    assert body == {
        "content": "回答一下缓存击穿",
        "model": "test-model",
        "client_request_id": "req-123",
    }


def test_send_message_reconciles_done_event_with_completed_turn(monkeypatch):
    monkeypatch.setattr(
        runner,
        "_iter_sse_events",
        lambda *args, **kwargs: [
            {"type": "turn_started", "turn_id": "turn-1"},
            {"type": "chunk", "content": "好的"},
            {"type": "done"},
        ],
    )
    monkeypatch.setattr(
        runner,
        "_get_turn_status",
        lambda *args, **kwargs: {"id": "turn-1", "status": "completed"},
    )

    result = runner.send_message_and_collect(
        "http://test",
        "token",
        "conversation-1",
        "回答一下缓存击穿",
        client_request_id="req-123",
    )

    assert result["client_request_id"] == "req-123"
    assert result["turn_id"] == "turn-1"
    assert result["terminal_event_type"] == "done"
    assert result["terminal_status"] == "completed"
    assert result["terminal_contract_error"] is None


def test_send_message_marks_terminal_status_mismatch_as_harness_error(monkeypatch):
    monkeypatch.setattr(
        runner,
        "_iter_sse_events",
        lambda *args, **kwargs: [
            {"type": "turn_started", "turn_id": "turn-1"},
            {"type": "done"},
        ],
    )
    monkeypatch.setattr(
        runner,
        "_get_turn_status",
        lambda *args, **kwargs: {"id": "turn-1", "status": "failed"},
    )

    result = runner.send_message_and_collect(
        "http://test",
        "token",
        "conversation-1",
        "回答一下缓存击穿",
        client_request_id="req-123",
    )

    assert result["terminal_contract_error"] == (
        "terminal event 'done' requires turn status 'completed', got 'failed'"
    )


def test_harness_contract_failure_overrides_a_passing_judge():
    scores = runner.apply_harness_contract(
        {"passed": True, "critical_issues": []},
        {"harness_contract_errors": ["turn status mismatch"]},
    )

    assert scores["passed"] is False
    assert scores["harness_contract_ok"] is False
    assert scores["critical_issues"] == ["Harness contract: turn status mismatch"]
