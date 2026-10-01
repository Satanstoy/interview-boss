"""Short, durable leases for upload workers that share a canonical pool."""

from __future__ import annotations


class UploadScopeLeaseError(RuntimeError):
    """Raised when a worker no longer owns the upload scope it would mutate."""


def _begin(conn):
    owns_transaction = not conn.in_transaction
    if owns_transaction:
        conn.execute("BEGIN IMMEDIATE")
    return owns_transaction


def _finish(conn, owns_transaction: bool, *, failed: bool = False):
    if not owns_transaction:
        return
    if failed:
        conn.rollback()
    else:
        conn.commit()


def acquire_upload_scope_lease(
    conn,
    scope_key: str,
    *,
    holder_token: str,
    lease_seconds: int = 120,
) -> dict | None:
    """Acquire an unheld/expired scope, incrementing its generation on takeover."""

    owns_transaction = _begin(conn)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO upload_scope_leases "
            "(scope_key, holder_token, generation, locked_until) "
            "VALUES (?, NULL, 0, NULL)",
            (str(scope_key),),
        )
        conn.execute(
            "UPDATE upload_scope_leases SET holder_token = ?, "
            "generation = generation + CASE WHEN holder_token = ? AND "
            "locked_until > CURRENT_TIMESTAMP THEN 0 ELSE 1 END, "
            "locked_until = datetime('now', ? ) WHERE scope_key = ? "
            "AND (holder_token IS NULL OR locked_until IS NULL "
            "OR locked_until <= CURRENT_TIMESTAMP OR holder_token = ?)",
            (
                holder_token,
                holder_token,
                f"+{max(1, int(lease_seconds))} seconds",
                str(scope_key),
                holder_token,
            ),
        )
        row = conn.execute(
            "SELECT scope_key, holder_token, generation, locked_until, "
            "CASE WHEN locked_until > CURRENT_TIMESTAMP THEN 1 ELSE 0 END AS lease_valid "
            "FROM upload_scope_leases WHERE scope_key = ?",
            (str(scope_key),),
        ).fetchone()
        acquired = (
            dict(row)
            if row
            and row["holder_token"] == holder_token
            and row["lease_valid"]
            else None
        )
        _finish(conn, owns_transaction)
        return acquired
    except Exception:
        _finish(conn, owns_transaction, failed=True)
        raise


def assert_upload_scope_lease(
    conn,
    scope_key: str,
    *,
    holder_token: str,
    generation: int,
) -> dict:
    row = conn.execute(
        "SELECT scope_key, holder_token, generation, locked_until, "
        "CASE WHEN locked_until > CURRENT_TIMESTAMP THEN 1 ELSE 0 END AS lease_valid "
        "FROM upload_scope_leases WHERE scope_key = ?",
        (str(scope_key),),
    ).fetchone()
    if (
        row is None
        or row["holder_token"] != holder_token
        or int(row["generation"]) != int(generation)
        or not row["lease_valid"]
    ):
        raise UploadScopeLeaseError(
            f"上传写入scope租约已失效: {scope_key} (generation={generation})"
        )
    return dict(row)


def heartbeat_upload_scope_lease(
    conn,
    scope_key: str,
    *,
    holder_token: str,
    generation: int,
    lease_seconds: int = 120,
) -> bool:
    owns_transaction = _begin(conn)
    try:
        cursor = conn.execute(
            "UPDATE upload_scope_leases SET locked_until = datetime('now', ?) "
            "WHERE scope_key = ? AND holder_token = ? AND generation = ? "
            "AND locked_until > CURRENT_TIMESTAMP",
            (
                f"+{max(1, int(lease_seconds))} seconds",
                str(scope_key),
                holder_token,
                int(generation),
            ),
        )
        _finish(conn, owns_transaction)
        return bool(cursor.rowcount)
    except Exception:
        _finish(conn, owns_transaction, failed=True)
        raise


def release_upload_scope_lease(
    conn,
    scope_key: str,
    *,
    holder_token: str,
    generation: int,
) -> bool:
    owns_transaction = _begin(conn)
    try:
        cursor = conn.execute(
            "UPDATE upload_scope_leases SET holder_token = NULL, locked_until = NULL "
            "WHERE scope_key = ? AND holder_token = ? AND generation = ?",
            (str(scope_key), holder_token, int(generation)),
        )
        _finish(conn, owns_transaction)
        return bool(cursor.rowcount)
    except Exception:
        _finish(conn, owns_transaction, failed=True)
        raise
