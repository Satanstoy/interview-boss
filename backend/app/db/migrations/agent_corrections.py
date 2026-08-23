"""Manual, auditable corrections for Agent interview questions."""

from __future__ import annotations

from app.core.interview_distribution_config import derive_job_family
from app.core.taxonomy import TAXONOMY_VERSION


AGENT_MANUAL_AUDIT_VERSION = "1.1-agent-manual"

# These are deliberately keyed by the stable public question IDs from the
# production question bank. Ambiguous/non-technical questions are omitted and
# remain Z1 for later review rather than being guessed during migration.
AGENT_MANUAL_CATEGORY_OVERRIDES: dict[int, tuple[str, str]] = {
    # Legacy distributed/cache/system questions.
    5872: ("F.评测、安全与运行", "F5.成本/延迟/质量权衡"),
    5902: ("E.语言与基础工程", "E5.框架/数据库/消息基础"),
    5903: ("E.语言与基础工程", "E5.框架/数据库/消息基础"),
    5905: ("E.语言与基础工程", "E5.框架/数据库/消息基础"),
    5907: ("E.语言与基础工程", "E5.框架/数据库/消息基础"),
    5934: ("F.评测、安全与运行", "F3.可观测性与可靠性"),
    5935: ("F.评测、安全与运行", "F3.可观测性与可靠性"),
    5940: ("F.评测、安全与运行", "F5.成本/延迟/质量权衡"),
    5976: ("F.评测、安全与运行", "F3.可观测性与可靠性"),
    6027: ("E.语言与基础工程", "E5.框架/数据库/消息基础"),
    6028: ("E.语言与基础工程", "E5.框架/数据库/消息基础"),
    6040: ("F.评测、安全与运行", "F5.成本/延迟/质量权衡"),
    6041: ("F.评测、安全与运行", "F3.可观测性与可靠性"),
    6042: ("E.语言与基础工程", "E5.框架/数据库/消息基础"),
    6051: ("F.评测、安全与运行", "F5.成本/延迟/质量权衡"),
    6052: ("F.评测、安全与运行", "F3.可观测性与可靠性"),
    6115: ("F.评测、安全与运行", "F2.安全/权限/隐私"),
    6134: ("F.评测、安全与运行", "F3.可观测性与可靠性"),
    6135: ("E.语言与基础工程", "E5.框架/数据库/消息基础"),
    6250: ("E.语言与基础工程", "E5.框架/数据库/消息基础"),
    6272: ("F.评测、安全与运行", "F3.可观测性与可靠性"),
    6273: ("E.语言与基础工程", "E5.框架/数据库/消息基础"),
    6304: ("E.语言与基础工程", "E5.框架/数据库/消息基础"),
    6305: ("F.评测、安全与运行", "F3.可观测性与可靠性"),
    6314: ("E.语言与基础工程", "E5.框架/数据库/消息基础"),
    6321: ("E.语言与基础工程", "E5.框架/数据库/消息基础"),
    6329: ("F.评测、安全与运行", "F5.成本/延迟/质量权衡"),
    6348: ("F.评测、安全与运行", "F5.成本/延迟/质量权衡"),
    6349: ("F.评测、安全与运行", "F5.成本/延迟/质量权衡"),
    6364: ("E.语言与基础工程", "E5.框架/数据库/消息基础"),
    6365: ("F.评测、安全与运行", "F5.成本/延迟/质量权衡"),
    # Legacy evaluation/security/optimization questions.
    5895: ("F.评测、安全与运行", "F3.可观测性与可靠性"),
    5897: ("F.评测、安全与运行", "F1.Agent评测与回归"),
    5898: ("B.LLM基础与Prompt", "B1.模型基础与推理"),
    5915: ("B.LLM基础与Prompt", "B1.模型基础与推理"),
    5917: ("F.评测、安全与运行", "F1.Agent评测与回归"),
    5982: ("F.评测、安全与运行", "F1.Agent评测与回归"),
    5983: ("F.评测、安全与运行", "F1.Agent评测与回归"),
    5984: ("F.评测、安全与运行", "F1.Agent评测与回归"),
    6019: ("F.评测、安全与运行", "F1.Agent评测与回归"),
    6021: ("F.评测、安全与运行", "F1.Agent评测与回归"),
    6037: ("B.LLM基础与Prompt", "B1.模型基础与推理"),
    6038: ("F.评测、安全与运行", "F2.安全/权限/隐私"),
    6047: ("F.评测、安全与运行", "F2.安全/权限/隐私"),
    6076: ("F.评测、安全与运行", "F2.安全/权限/隐私"),
    6124: ("F.评测、安全与运行", "F5.成本/延迟/质量权衡"),
    6147: ("F.评测、安全与运行", "F2.安全/权限/隐私"),
    6268: ("F.评测、安全与运行", "F1.Agent评测与回归"),
    6278: ("F.评测、安全与运行", "F5.成本/延迟/质量权衡"),
    6294: ("F.评测、安全与运行", "F1.Agent评测与回归"),
    6339: ("F.评测、安全与运行", "F1.Agent评测与回归"),
    6358: ("F.评测、安全与运行", "F3.可观测性与可靠性"),
    6359: ("F.评测、安全与运行", "F1.Agent评测与回归"),
    6360: ("F.评测、安全与运行", "F1.Agent评测与回归"),
    # Legacy algorithm questions: E2 means algorithm implementation, not data structures.
    5889: ("G.算法与数据结构", "G2.算法手撕"),
    5890: ("G.算法与数据结构", "G2.算法手撕"),
    5998: ("G.算法与数据结构", "G2.算法手撕"),
    5999: ("G.算法与数据结构", "G2.算法手撕"),
    6000: ("G.算法与数据结构", "G2.算法手撕"),
    6096: ("G.算法与数据结构", "G2.算法手撕"),
    6242: ("G.算法与数据结构", "G2.算法手撕"),
    6252: ("G.算法与数据结构", "G2.算法手撕"),
    6306: ("G.算法与数据结构", "G2.算法手撕"),
    # Clear technical questions that were previously left in Z1.
    5875: ("E.语言与基础工程", "E5.框架/数据库/消息基础"),
    6045: ("E.语言与基础工程", "E6.操作系统与网络"),
    6086: ("E.语言与基础工程", "E5.框架/数据库/消息基础"),
    6088: ("G.算法与数据结构", "G2.算法手撕"),
    6113: ("E.语言与基础工程", "E2.Python异步与并发"),
    6133: ("E.语言与基础工程", "E4.Java并发与JVM"),
}


def _migration_107_agent_taxonomy_corrections(conn):
    """Apply only reviewed Agent question corrections, with an audit trail."""
    columns = {
        row[1] for row in conn.execute("PRAGMA table_info('question_bank')").fetchall()
    }
    deleted_column = ", deleted_at" if "deleted_at" in columns else ""
    rows = conn.execute(
        "SELECT id, cat1, cat2, job_position" + deleted_column + " FROM question_bank "
        "WHERE id IN ({})".format(",".join("?" * len(AGENT_MANUAL_CATEGORY_OVERRIDES))),
        tuple(AGENT_MANUAL_CATEGORY_OVERRIDES),
    ).fetchall()
    changed = 0
    for row in rows:
        if derive_job_family(row["job_position"]) != "agent_llm":
            continue
        if deleted_column and row["deleted_at"] is not None:
            continue
        target_cat1, target_cat2 = AGENT_MANUAL_CATEGORY_OVERRIDES[row["id"]]
        old_cat1, old_cat2 = row["cat1"] or "", row["cat2"] or ""
        if (old_cat1, old_cat2) == (target_cat1, target_cat2):
            continue
        conn.execute(
            "UPDATE question_bank SET cat1 = ?, cat2 = ?, taxonomy_version = ?, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (target_cat1, target_cat2, TAXONOMY_VERSION, row["id"]),
        )
        conn.execute(
            "INSERT INTO taxonomy_migration_audit "
            "(migration_version, table_name, record_id, old_cat1, old_cat2, "
            "new_cat1, new_cat2, reason) VALUES (?, 'question_bank', ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(migration_version, table_name, record_id) DO UPDATE SET "
            "old_cat1 = excluded.old_cat1, old_cat2 = excluded.old_cat2, "
            "new_cat1 = excluded.new_cat1, new_cat2 = excluded.new_cat2, "
            "reason = excluded.reason",
            (
                AGENT_MANUAL_AUDIT_VERSION,
                row["id"],
                old_cat1,
                old_cat2,
                target_cat1,
                target_cat2,
                "manual_agent_review",
            ),
        )
        changed += 1
    return changed
