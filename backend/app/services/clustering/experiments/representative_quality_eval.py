"""代表题质量评估：现有聚类的代表题是否真的涵盖其子类（oq 变体）。

对每个 frequency>1 的代表题，LLM 逐变体核验：
1. 变体与代表题考察点是否一致（一致 = 合理并入；不一致 = 误合并脏数据）
2. 代表题是否能涵盖所有一致变体的考察点
3. 变体间重复

运行：docker compose run --rm -v $PWD/backend:/app/backend backend python -m app.services.clustering.experiments.representative_quality_eval
输出：backend/experiment_reports/representative_quality_eval.md
"""
import asyncio
import json
import os
import time

from app.db.connection import get_db_connection

REPORT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "experiment_reports"))
SAMPLE_N = 15

EVAL_PROMPT = """你是面试题去重专家。以下是一个【题目聚类】：代表题 + 它的原始题面变体列表。

请评估该聚类的质量：
1. 每个变体与代表题的**考察点是否一致**（一致 = 是同一道面试题的不同表述；不一致 = 虽然相关但考察点不同，属于误合并）
2. 代表题是否能**涵盖所有一致变体的考察点**（代表题本身是否足够规范、完整）
3. 变体之间是否有**重复**（完全相同或高度重复）

【代表题】
{representative}

【变体列表】
{variants}

输出格式（严格 JSON）：
{{"variants": [{{"index": 0, "consistent": true, "reason": "一句话"}}],
  "representative_covers_all": true,
  "duplicates": [变体index数组],
  "representative_quality": "优/良/差 + 一句话"}}"""


def load_representatives(limit=60):
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT id, question, frequency, original_questions FROM question_bank "
        "WHERE deleted_at IS NULL AND frequency > 1 "
        "ORDER BY frequency DESC LIMIT ?",
        (limit,),
    ).fetchall()
    out = []
    for r in rows:
        try:
            oq = json.loads(r["original_questions"] or "[]")
        except Exception:
            oq = []
        oq = [str(q).strip() for q in oq if str(q).strip()]
        if not oq:
            continue
        out.append({"id": r["id"], "question": r["question"], "freq": r["frequency"], "oq": oq})
    return out


def parse_json(raw):
    import re
    text = (raw or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                return None
    return None


async def llm_call(prompt):
    from app.services.llm import _call_llm_with_retry
    return await _call_llm_with_retry(
        prompt, system_msg="你是一个面试题去重专家。", response_format=None, user_id=1, model=None,
    )


async def main():
    os.makedirs(REPORT_DIR, exist_ok=True)
    t0 = time.monotonic()
    reps = load_representatives(limit=60)
    sample = reps[:SAMPLE_N]
    print(f"[eval] 代表题（frequency>1）总数 {len(reps)}，抽样 {len(sample)} 个评估")

    sem = asyncio.Semaphore(4)

    async def limited(prompt):
        async with sem:
            return await llm_call(prompt)

    total_variants = 0
    inconsistent = 0
    duplicates = 0
    covers_all = 0
    quality_issues = []

    lines = ["# 代表题质量评估（代表题 vs oq 变体一致性）", "",
             f"**时间**: {time.strftime('%Y-%m-%d %H:%M:%S')}  **耗时**: 进行中", "",
             f"- 抽样: {len(sample)} 个聚类（frequency>1 代表题）", ""]

    for rep in sample:
        variants_text = "\n".join(f"{i}. {v}" for i, v in enumerate(rep["oq"]))
        prompt = EVAL_PROMPT.format(representative=rep["question"], variants=variants_text)
        raw = await limited(prompt)
        data = parse_json(raw) or {}
        v_results = data.get("variants", []) if isinstance(data, dict) else []
        v_map = {v.get("index"): v for v in v_results if isinstance(v, dict)}
        dup_idx = set(data.get("duplicates", []) or []) if isinstance(data, dict) else set()
        covers = bool(data.get("representative_covers_all")) if isinstance(data, dict) else False

        n_variants = len(rep["oq"])
        total_variants += n_variants
        bad = sum(1 for i in range(n_variants) if not v_map.get(i, {}).get("consistent", True))
        inconsistent += bad
        duplicates += len(dup_idx)
        if covers:
            covers_all += 1
        else:
            quality_issues.append(rep["id"])

        lines += [
            f"## 聚类 {rep['id']}（frequency={rep['freq']}，变体 {n_variants} 个）",
            f"- 代表题: {rep['question']}",
            f"- 涵盖所有变体: {'✅' if covers else '❌'} | 质量: {data.get('representative_quality', '?')}",
            "",
        ]
        for i, v in enumerate(rep["oq"]):
            info = v_map.get(i, {})
            consistent = info.get("consistent", True)
            mark = "✅" if consistent else "🔴"
            dup_mark = " [重复]" if i in dup_idx else ""
            lines.append(f"- {mark}{dup_mark} 变体{i}: {v[:60]}{'...' if len(v) > 60 else ''}"
                         f"（{info.get('reason', '')[:40]}）")
        lines.append("")
        print(f"[eval] 聚类{rep['id']}: {n_variants}变体, 不一致{bad}, 重复{len(dup_idx)}, 涵盖{covers}")

    lines += ["## 汇总", "",
              f"- 评估聚类: {len(sample)} 个",
              f"- 总变体: {total_variants} 个",
              f"- **不一致变体（误合并脏数据）**: {inconsistent} 个（{inconsistent / max(total_variants, 1) * 100:.1f}%）",
              f"- **重复变体**: {duplicates} 个（{duplicates / max(total_variants, 1) * 100:.1f}%）",
              f"- **代表题涵盖全部变体**: {covers_all}/{len(sample)}（{covers_all / max(len(sample), 1) * 100:.0f}%）",
              f"- 代表题未涵盖的聚类: {quality_issues}", ""]
    path = os.path.join(REPORT_DIR, "representative_quality_eval.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"[eval] 报告已写入 {path}，耗时 {time.monotonic() - t0:.0f}s")


if __name__ == "__main__":
    asyncio.run(main())
