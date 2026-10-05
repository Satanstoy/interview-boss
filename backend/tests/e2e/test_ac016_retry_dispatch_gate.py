import sqlite3

from e2e.ac016_retry_dispatch_gate import retry_dispatch_state


def _connect():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE jobs (
            id INTEGER PRIMARY KEY,
            job_type TEXT NOT NULL,
            status TEXT NOT NULL,
            arq_job_id TEXT,
            idempotency_key TEXT
        );
        CREATE TABLE job_payloads (job_id INTEGER PRIMARY KEY, payload TEXT NOT NULL);
        CREATE TABLE analysis_queue (
            contribution_request_id INTEGER,
            status TEXT NOT NULL
        );
        CREATE TABLE public_contribution_requests (
            id INTEGER PRIMARY KEY,
            status TEXT NOT NULL
        );
        """
    )
    return conn


def test_existing_dispatched_cluster_window_covers_rootless_retry():
    conn = _connect()
    conn.execute(
        "INSERT INTO jobs VALUES (3, 'cluster_batch', 'queued', 'arq-3', "
        "'cluster-window:1:abc')"
    )
    conn.execute(
        "INSERT INTO job_payloads VALUES (3, '{\"queue_scope\":\"public_contribution\"}')"
    )
    conn.execute("INSERT INTO analysis_queue VALUES (22, 'pending')")

    assert retry_dispatch_state(conn, 22) == "dispatched"


def test_pending_retry_job_is_waiting_for_dispatcher():
    conn = _connect()
    conn.execute(
        "INSERT INTO jobs VALUES (4, 'cluster_batch', 'pending', NULL, 'retry:22:abc')"
    )
    conn.execute(
        "INSERT INTO job_payloads VALUES (4, '{\"queue_scope\":\"public_contribution\"}')"
    )
    conn.execute("INSERT INTO analysis_queue VALUES (22, 'pending')")

    assert retry_dispatch_state(conn, 22) == "pending"


def test_unrelated_or_missing_queue_job_is_not_a_retry():
    conn = _connect()
    conn.execute(
        "INSERT INTO jobs VALUES (5, 'cluster_batch', 'queued', 'arq-5', "
        "'cluster-window:1:other')"
    )
    conn.execute(
        "INSERT INTO job_payloads VALUES (5, '{\"queue_scope\":\"public_contribution\"}')"
    )
    conn.execute("INSERT INTO analysis_queue VALUES (99, 'pending')")

    assert retry_dispatch_state(conn, 22) == "missing"


def test_completed_shared_cluster_window_releases_browser_gate():
    conn = _connect()
    conn.execute(
        "INSERT INTO jobs VALUES (6, 'cluster_batch', 'completed', 'arq-6', "
        "'cluster-window:1:finished')"
    )
    conn.execute(
        "INSERT INTO job_payloads VALUES (6, '{\"queue_scope\":\"public_contribution\"}')"
    )
    conn.execute("INSERT INTO analysis_queue VALUES (22, 'done')")
    conn.execute("INSERT INTO public_contribution_requests VALUES (22, 'published')")

    assert retry_dispatch_state(conn, 22) == "completed"
