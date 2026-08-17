"""生产 matcher（带 cluster_label 新方法）mock 增量聚类评估。

设计：从 agent 题库（B.Agent与LLM应用）抽 10 题作为"新题"（mock 增量），
其余全部题作为"已有聚类"；用生产 match_new_questions 跑匹配，
ground truth = 每题原本所属的聚类代表题（original_questions 关系），
评估"匹配到正确聚类"的质量。

运行：docker compose run --rm -v $PWD/backend:/app/backend backend python -m app.services.clustering.experiments.mock_incremental_eval
"""

import asyncio
import json
import os
import time

from app.db.connection import get_db_connection

REPORT_DIR = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "..", "experiment_reports"
    )
)
SAMPLE_N = 10
CAT1 = "B.Agent与LLM应用"


def load_all_questions():
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT id, question, cat1, cat2, tags, frequency, original_questions, cluster_label "
        "FROM question_bank WHERE deleted_at IS NULL ORDER BY id"
    ).fetchall()
    out = []
    for r in rows:
        oq = []
        try:
            oq = json.loads(r["original_questions"] or "[]")
        except Exception:
            pass
        out.append(
            {
                "id": r["id"],
                "question": r["question"],
                "cat1": r["cat1"] or "",
                "cat2": r["cat2"] or "",
                "tags": r["tags"] or "",
                "frequency": r["frequency"] or 1,
                "oq": [str(x) for x in oq if str(x).strip()],
                "cluster_label": r["cluster_label"],
            }
        )
    return out


def build_ground_truth(qs):
    """题面 → 它所属聚类的代表题 id（frequency>1 的代表题；孤岛 → None）。

    代表题被抽作"新题"后，正确行为是**保持独立**（未匹配）——它自己就是聚类；
    匹配到任何已有聚类 = 误合并（会把原聚类合并走）。
    """
    truth = {}
    for q in qs:
        if q["frequency"] > 1:
            truth[q["question"]] = q["id"]
            for oq_text in q["oq"]:
                truth.setdefault(oq_text, q["id"])
    return truth


def is_representative(q):
    return q["frequency"] > 1


def pick_sample(qs):
    """从 agent 分类抽 10 题：优先混合 cluster 成员与孤岛。"""
    cat2_qs = [q for q in qs if q["cat1"] == CAT1]
    # 孤岛（frequency=1）与 cluster 成员都要有
    islands = [q for q in cat2_qs if q["frequency"] == 1]
    members = [q for q in cat2_qs if q["frequency"] > 1]
    sample = []
    # 优先抽 cluster 代表题（有 ground truth 的）
    for q in members[: SAMPLE_N // 2]:
        sample.append(q)
    for q in islands[: SAMPLE_N - len(sample)]:
        sample.append(q)
    return sample


async def main():
    os.makedirs(REPORT_DIR, exist_ok=True)
    t0 = time.monotonic()
    qs = load_all_questions()
    print(
        f"[eval] 题库 {len(qs)} 题（{CAT1}: {sum(1 for q in qs if q['cat1'] == CAT1)} 题）"
    )

    sample = pick_sample(qs)
    sample_ids = {q["id"] for q in sample}
    print(f"[eval] mock 新题 {len(sample)} 道: {sorted(sample_ids)}")

    existing = [q for q in qs if q["id"] not in sample_ids]

    # 构造 existing_clusters_by_cat2（按 cat2 分组，只有代表题作候选）
    from collections import defaultdict

    existing_clusters_by_cat2 = defaultdict(list)
    for q in existing:
        if q["frequency"] > 1:  # 代表题才是候选
            existing_clusters_by_cat2[q["cat2"]].append(
                {
                    "id": q["id"],
                    "question": q["question"],
                    "cat1": q["cat1"],
                    "cat2": q["cat2"],
                    "tags": q["tags"],
                    "cluster_label": q["cluster_label"],
                }
            )

    new_rows = [
        {
            "id": q["id"],
            "question": q["question"],
            "cat1": q["cat1"],
            "cat2": q["cat2"],
            "tags": q["tags"],
        }
        for q in sample
    ]

    from app.services.clustering.matcher import match_new_questions

    result = await match_new_questions(
        new_rows, dict(existing_clusters_by_cat2), user_id=1
    )

    matched = result["matched"]
    unmatched = result["unmatched"]
    print(f"[eval] 匹配: {len(matched)} 道 / 未匹配: {len(unmatched)} 道")

    lines = [
        "# 生产 matcher mock 增量聚类评估（cluster_label 新方法）",
        "",
        f"**时间**: {time.strftime('%Y-%m-%d %H:%M:%S')}  **耗时**: {time.monotonic() - t0:.0f}s",
        "",
        f"- 题库: {len(qs)} 题 | mock 新题: {len(sample)} 道（{CAT1}）",
        "",
        f"- 匹配: **{len(matched)}** 道 | 未匹配: **{len(unmatched)}** 道",
        "",
        "## 每题匹配明细（ground truth = 原所属聚类代表题）",
        "",
    ]

    def q_text(qid):
        return next((q["question"] for q in qs if q["id"] == qid), f"(缺失 {qid})")

    false_merges = 0
    reps_matched = 0
    islands_matched = 0
    for m in matched:
        nid_int = m.get("new_id")
        cid_int = m.get("question_bank_id")
        if nid_int is None or cid_int is None:
            continue
        nq = next((q for q in sample if q["id"] == nid_int), None)
        if nq is None:
            continue
        if is_representative(nq):
            reps_matched += 1
            false_merges += 1
            mark = "🔴"
        else:
            islands_matched += 1
            mark = "🟢"
        lines += [
            f"### {mark} 新题 {nid_int} → 聚类 {cid_int}",
            f"- 新题: {q_text(nid_int)}",
            f"- 目标代表题: {q_text(cid_int)}",
            f"- 类型: {'代表题（应保持独立，匹配=误合并）' if is_representative(nq) else '孤岛（人工核验合理性）'}",
            "",
        ]
    reps_total = sum(1 for q in sample if is_representative(q))
    for u in unmatched:
        nid = u.get("id")
        nq = next((q for q in sample if q["id"] == nid), None)
        is_rep = is_representative(nq) if nq else False
        lines += [
            f"### {'🟢' if is_rep else '🟡'} 未匹配 {nid}",
            f"- 新题: {q_text(int(nid)) if str(nid).isdigit() else nid}",
            f"- 类型: {'代表题（保持独立 = 正确）' if is_rep else '孤岛（保持独立，人工核验是否漏合并）'}",
            "",
        ]

    lines += [
        "## 结论",
        "",
        f"- 代表题（应保持独立）: **{reps_total}** 道",
        f"  - 误合并（被并入其他聚类）: **{false_merges}** 道",
        f"  - 保持独立: **{reps_total - false_merges}** 道",
        f"- 孤岛（原系统未合并，新方法语义匹配供人工核验）: 匹配 {islands_matched} 道",
        f"- 未匹配总数: {len(unmatched)} 道（可能为新主题）",
        "",
    ]
    path = os.path.join(REPORT_DIR, "mock_incremental_eval.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"[eval] 报告已写入 {path}，耗时 {time.monotonic() - t0:.0f}s")


if __name__ == "__main__":
    asyncio.run(main())
