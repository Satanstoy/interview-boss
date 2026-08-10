# Cluster Memory-Label Experiment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 独立实验"cluster 语义标签摘要记忆"聚类算法（LLM-MemCluster 模式），用生产数据量化对比现有聚类方案，效果经用户核验后再决定是否并入生产。

**Architecture:** 不修改任何生产聚类代码。在 `backend/app/services/clustering/experiments/` 新建独立实验包：加载生产 DB 的现有聚类（134 个有合并记录的 cluster）和孤岛题（187 个 frequency=1），为每个 cluster 生成 LLM 语义标签摘要，让孤岛题增量分配归属（文本预筛 + LLM 决策），输出量化对比报告。核心算法模块带 mock-LLM 单元测试（TDD）；评估脚本一次性运行。

**Tech Stack:** Python 3.10 / FastAPI 项目现有 `app.services.llm` 封装 / 现有 `_normalize_question_text` 工具 / pytest（Docker test-runtime）/ 生产 SQLite（只读）。

**数据事实（勘察结论，2026-08-05）：**
- `question_bank` 321 题；`cluster_id` = 代表题自身 ID，聚类关系在 `original_questions` JSON 字段
- 187 题 frequency=1（孤岛，58%），134 题 frequency>1（有合并记录）
- 存在真实误合并样本（id 5872 "高并发限流" 的 oq 混入无关行为面题）——实验报告中抽样供核验
- `analysis_queue` 全部 done；`questions_detail` 566 条活跃

**实验评估方式（用户已确认）：** 生产数据量化对比。指标：孤岛题被合并数、合并对语义合理性（抽样 25 个人工核验）、LLM 调用次数/token 估算、耗时。

**运行方式：**
- 单元测试：`docker compose --profile test run --rm test uv run pytest backend/tests/services/clustering/experiments/ -q`
- 实验运行：`docker compose run --rm backend python -m app.services.clustering.experiments.evaluate`
- 报告输出：`backend/experiment_reports/round<N>.md`（加入 .gitignore，不提交生产数据）

**不做的（YAGNI）：** 不碰 `matcher.py`/`clusterer.py`/`batch.py` 生产代码；不做前端；不做异步化（第一阶段已另行规划）；不生成 embedding。

---

## 文件结构

| 文件 | 职责 |
|------|------|
| `backend/app/services/clustering/experiments/__init__.py` | 空包 |
| `backend/app/services/clustering/experiments/prompts.py` | 实验 prompt：`CLUSTER_LABEL_PROMPT`（摘要生成）、`SINGLETON_ASSIGN_PROMPT`（增量分配） |
| `backend/app/services/clustering/experiments/memory_labels.py` | 核心逻辑：`load_cluster_data()`、`text_prefilter()`、`generate_cluster_labels()`、`assign_singletons()` |
| `backend/app/services/clustering/experiments/evaluate.py` | 评估入口：主流程 + Markdown 报告（`python -m` 可执行） |
| `backend/tests/services/clustering/experiments/__init__.py` | 空包 |
| `backend/tests/services/clustering/experiments/test_memory_labels.py` | mock-LLM 单元测试 |
| `.gitignore` | 追加 `backend/experiment_reports/` |

---

### Task 1: 实验包骨架 + 数据加载器

**Files:**
- Create: `backend/app/services/clustering/experiments/__init__.py`
- Create: `backend/app/services/clustering/experiments/memory_labels.py`
- Test: `backend/tests/services/clustering/experiments/__init__.py`
- Test: `backend/tests/services/clustering/experiments/test_memory_labels.py`

- [ ] **Step 1: 写失败测试 `test_load_cluster_data`**

```python
"""mock-LLM 单元测试：数据加载与纯逻辑函数（不调真实 LLM）"""
import pytest


def _seed_db(conn):
    """构造最小实验数据：2 个有合并记录的 cluster + 1 个孤岛"""
    conn.execute("""
        CREATE TABLE question_bank (
            id INTEGER PRIMARY KEY, question TEXT, cat1 TEXT, cat2 TEXT,
            frequency INTEGER, original_questions TEXT, job_position TEXT,
            deleted_at TEXT, owner_id INTEGER
        )
    """)
    rows = [
        # id, question, cat1, cat2, frequency, original_questions, job_position, deleted_at, owner_id
        (1, "高并发场景下怎样做限流？", "Java", "并发", 3,
         '["怎样做限流？", "限流方案有哪些"]', "后端开发", None, None),
        (2, "Java 线程池的工作原理", "Java", "并发", 2,
         '["线程池原理"]', "后端开发", None, None),
        (3, "介绍一下 MySQL 索引", "数据库", "索引", 1,
         '["MySQL 索引"]', "后端开发", None, None),
    ]
    conn.executemany(
        "INSERT INTO question_bank (id, question, cat1, cat2, frequency, original_questions, job_position, deleted_at, owner_id) VALUES (?,?,?,?,?,?,?,?,?)",
        rows,
    )
    conn.commit()


def test_load_cluster_data_splits_clusters_and_singletons(test_db):
    _seed_db(test_db)
    from app.services.clustering.experiments.memory_labels import load_cluster_data

    clusters, singletons = load_cluster_data(test_db)

    assert len(clusters) == 2  # frequency > 1 的是已知 cluster
    assert len(singletons) == 1  # frequency == 1 的是孤岛
    cluster_ids = {c["qb_id"] for c in clusters}
    assert cluster_ids == {1, 2}
    assert singletons[0]["qb_id"] == 3
    # cluster 必须带原始题列表（去重后）
    c1 = next(c for c in clusters if c["qb_id"] == 1)
    assert "怎样做限流？" in c1["oq"]
    assert c1["cat2"] == "并发"


def test_load_cluster_data_skips_deleted_and_keeps_oq(test_db):
    _seed_db(test_db)
    from app.services.clustering.experiments.memory_labels import load_cluster_data

    test_db.execute("UPDATE question_bank SET deleted_at = datetime('now') WHERE id = 2")
    test_db.commit()
    clusters, singletons = load_cluster_data(test_db)

    assert [c["qb_id"] for c in clusters] == [1]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `docker compose --profile test run --rm test uv run pytest backend/tests/services/clustering/experiments/test_memory_labels.py::test_load_cluster_data_splits_clusters_and_singletons -q`
Expected: FAIL（ModuleNotFoundError: app.services.clustering.experiments）

- [ ] **Step 3: 实现数据加载器**

Create `backend/app/services/clustering/experiments/__init__.py`（空文件）。

Create `backend/app/services/clustering/experiments/memory_labels.py`:

```python
"""cluster 语义标签摘要记忆 — 实验模块（独立于生产聚类代码）。

实验思路（对齐 LLM-MemCluster / Lifecycle-Aware Clustering）：
为每个已有 cluster 维护 LLM 生成的语义标签摘要，新题按"聚类转分类"方式
增量分配，绕开 embedding 几何距离依赖。评估通过 evaluate.py 跑全流程。
"""
import json
import logging

logger = logging.getLogger("interview-boss")


def load_cluster_data(conn) -> tuple[list[dict], list[dict]]:
    """加载实验数据。

    Returns:
        (clusters, singletons):
        - clusters: frequency > 1 的已知 cluster，含代表题与 original_questions
        - singletons: frequency == 1 的孤岛题（模拟待聚合的新题）
    """
    rows = conn.execute(
        "SELECT id, question, cat1, cat2, frequency, original_questions "
        "FROM question_bank "
        "WHERE deleted_at IS NULL "
        "ORDER BY id"
    ).fetchall()
    clusters, singletons = [], []
    for r in rows:
        item = {
            "qb_id": r["id"],
            "question": r["question"],
            "cat1": r["cat1"] or "",
            "cat2": r["cat2"] or "",
            "freq": r["frequency"] or 1,
        }
        oq_raw = r["original_questions"] or "[]"
        try:
            oq = json.loads(oq_raw) if isinstance(oq_raw, str) else []
        except (json.JSONDecodeError, TypeError):
            oq = []
        oq = [str(q).strip() for q in oq if str(q).strip()]
        item["oq"] = oq
        if item["freq"] > 1:
            clusters.append(item)
        else:
            singletons.append(item)
    return clusters, singletons
```

- [ ] **Step 4: 运行测试确认通过**

Run: `docker compose --profile test run --rm test uv run pytest backend/tests/services/clustering/experiments/test_memory_labels.py -q`
Expected: PASS（2 passed）

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/clustering/experiments/ backend/tests/services/clustering/experiments/
git commit -m "feat(experiments): cluster memory-label experiment skeleton + data loader"
```

---

### Task 2: 文本预筛（确定性分配）

新算法第一层：规范化文本精确匹配 + 子串/包含匹配，零成本确定归属（复用生产 `_normalize_question_text`），减少 LLM 调用。

**Files:**
- Modify: `backend/app/services/clustering/experiments/memory_labels.py`
- Test: `backend/tests/services/clustering/experiments/test_memory_labels.py`

- [ ] **Step 1: 写失败测试**

```python
def test_text_prefilter_exact_and_substring(test_db):
    _seed_db(test_db)
    from app.services.clustering.experiments.memory_labels import load_cluster_data, text_prefilter

    clusters, singletons = load_cluster_data(test_db)
    # 孤岛题与 cluster 1 文本完全相同
    singletons.append({"qb_id": 99, "question": "高并发场景下怎样做限流？", "cat1": "", "cat2": "", "freq": 1, "oq": []})

    matches = text_prefilter(singletons, clusters)
    # 完全一致的归到 cluster 1
    assert matches[99] == 1


def test_text_prefilter_returns_empty_for_unrelated(test_db):
    _seed_db(test_db)
    from app.services.clustering.experiments.memory_labels import load_cluster_data, text_prefilter

    clusters, singletons = load_cluster_data(test_db)
    # id=3 的孤岛 "介绍一下 MySQL 索引" 与两个 cluster 无关
    matches = text_prefilter(singletons, clusters)
    assert 3 not in matches
```

- [ ] **Step 2: 运行测试确认失败**

Run: `docker compose --profile test run --rm test uv run pytest backend/tests/services/clustering/experiments/test_memory_labels.py::test_text_prefilter_exact_and_substring -q`
Expected: FAIL（ImportError: cannot import name 'text_prefilter'）

- [ ] **Step 3: 实现 text_prefilter**

在 `memory_labels.py` 追加：

```python
from app.services.clustering.clusterer import _normalize_question_text


def text_prefilter(singletons: list[dict], clusters: list[dict]) -> dict[int, int]:
    """文本级确定性分配：孤岛题 → 已有 cluster。

    匹配规则（按优先级）：
    1. 规范化文本精确相等
    2. 一方包含另一方（长度 >= 8 时）
    Returns: {singleton_qb_id: cluster_qb_id}
    """
    norm_clusters = {_normalize_question_text(c["question"]): c["qb_id"] for c in clusters}
    matches: dict[int, int] = {}
    for s in singletons:
        s_norm = _normalize_question_text(s["question"])
        if not s_norm:
            continue
        if s_norm in norm_clusters:
            matches[s["qb_id"]] = norm_clusters[s_norm]
            continue
        for c_norm, c_qb_id in norm_clusters.items():
            if len(s_norm) >= 8 and len(c_norm) >= 8 and (
                s_norm in c_norm or c_norm in s_norm
            ):
                matches[s["qb_id"]] = c_qb_id
                break
    return matches
```

- [ ] **Step 4: 运行测试确认通过**

Run: `docker compose --profile test run --rm test uv run pytest backend/tests/services/clustering/experiments/test_memory_labels.py -q`
Expected: PASS（4 passed）

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/clustering/experiments/memory_labels.py backend/tests/services/clustering/experiments/test_memory_labels.py
git commit -m "feat(experiments): deterministic text prefilter for singleton assignment"
```

---

### Task 3: cluster 语义标签摘要生成（LLM）

**Files:**
- Create: `backend/app/services/clustering/experiments/prompts.py`
- Modify: `backend/app/services/clustering/experiments/memory_labels.py`
- Test: `backend/tests/services/clustering/experiments/test_memory_labels.py`

- [ ] **Step 1: 写失败测试**

```python
def test_generate_cluster_labels_parses_llm_json(monkeypatch, test_db):
    _seed_db(test_db)
    from app.services.clustering.experiments.memory_labels import (
        load_cluster_data, generate_cluster_labels,
    )

    async def fake_llm(prompt, system_msg, response_format, user_id, model):
        return json.dumps([
            {"qb_id": 1, "label": "高并发限流方案", "keywords": ["限流", "高并发", "网关"]},
            {"qb_id": 2, "label": "Java 线程池", "keywords": ["线程池", "JUC"]},
        ], ensure_ascii=False)

    monkeypatch.setattr(
        "app.services.clustering.experiments.memory_labels._call_llm_with_retry",
        fake_llm,
    )
    clusters, _ = load_cluster_data(test_db)
    labels = generate_cluster_labels(clusters, user_id=None)

    assert labels[1] == "高并发限流方案"
    assert labels[2] == "Java 线程池"


def test_generate_cluster_labels_falls_back_to_question(monkeypatch, test_db):
    """LLM 失败/缺字段时，回退用代表题文本，绝不中断"""
    _seed_db(test_db)
    from app.services.clustering.experiments.memory_labels import (
        load_cluster_data, generate_cluster_labels,
    )

    async def broken_llm(prompt, system_msg, response_format, user_id, model):
        raise RuntimeError("llm down")

    monkeypatch.setattr(
        "app.services.clustering.experiments.memory_labels._call_llm_with_retry",
        broken_llm,
    )
    clusters, _ = load_cluster_data(test_db)
    labels = generate_cluster_labels(clusters, user_id=None)

    assert labels[1].startswith("高并发")  # 回退到代表题文本
    assert len(labels) == 2
```

- [ ] **Step 2: 运行测试确认失败**

Run: `docker compose --profile test run --rm test uv run pytest backend/tests/services/clustering/experiments/test_memory_labels.py::test_generate_cluster_labels_parses_llm_json -q`
Expected: FAIL（ImportError: cannot import name 'generate_cluster_labels'）

- [ ] **Step 3: 实现 prompts.py + generate_cluster_labels**

Create `backend/app/services/clustering/experiments/prompts.py`:

```python
"""cluster 语义标签摘要记忆 — 实验 prompt"""

CLUSTER_LABEL_PROMPT = """你是面试题题库管理专家。下面是一批【已有题目聚类】的原始题面列表，请为每个聚类生成一个**规范标签**。

要求：
1. label：用一句话概括该聚类的规范题面（20 字以内，作为该聚类的"记忆标签"）
2. keywords：3-6 个关键词，覆盖该聚类下所有原始题面
3. 只输出 JSON 数组，不要输出其他内容

输入格式（每行一个聚类）：
{qb_id} | {questions}

输出格式：
[{{"qb_id": {qb_id}, "label": "...", "keywords": ["...", "..."]}}, ...]"""

SINGLETON_ASSIGN_PROMPT = """你是面试题去重专家。下面有一道【新题目】和一批【已有聚类标签】。请判断新题目应该归入哪个已有聚类，还是作为独立新题。

判断标准：
- 只合并**语义上确属同一道面试题**的（表述不同但考察点相同的）
- 内容相近但考察点不同的（如"限流实现" vs "限流算法对比"）不要合并
- 没有匹配时不要强行归入，返回 null

输出格式（严格 JSON，不要输出其他内容）：
{{"match": {qb_id} 或 null, "reason": "一句话原因"}}"""
```

在 `memory_labels.py` 追加：

```python
import asyncio

from app.services.llm import _call_llm_with_retry
from app.services.clustering.experiments.prompts import CLUSTER_LABEL_PROMPT

LABELS_PER_BATCH = 20


async def generate_cluster_labels(clusters: list[dict], user_id: int | None) -> dict[int, str]:
    """为每个 cluster 生成语义标签摘要。

    Returns: {cluster_qb_id: label_text}
    任何 cluster 失败都回退为代表题文本，保证 100% 覆盖率。
    """
    labels: dict[int, str] = {}
    for i in range(0, len(clusters), LABELS_PER_BATCH):
        batch = clusters[i : i + LABELS_PER_BATCH]
        lines = "\n".join(
            f"{c['qb_id']} | {c['question']} | " + " | ".join(c["oq"][:6])
            for c in batch
        )
        prompt = CLUSTER_LABEL_PROMPT.format(qb_id="{qb_id}", questions=lines)
        try:
            raw = await _call_llm_with_retry(
                prompt,
                system_msg="你是一个面试题题库管理专家。",
                response_format={"type": "json_object"},
                user_id=user_id,
            )
            parsed = _extract_json_array(raw)
            for item in parsed:
                qid = int(item.get("qb_id"))
                label = (item.get("label") or "").strip()
                if qid and label:
                    labels[qid] = label
        except Exception as e:
            logger.warning(f"[experiment] 标签摘要生成失败，回退代表题: {e}")
        for c in batch:
            labels.setdefault(c["qb_id"], c["question"][:40])
    return labels


def _extract_json_array(raw: str) -> list[dict]:
    """从 LLM 输出提取 JSON 数组（容忍 markdown 代码块包裹）"""
    import re

    text = (raw or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            # 兼容 {"clusters": [...]} 包裹
            data = data.get("clusters") or data.get("items") or []
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        m = re.search(r"\[.*\]", text, re.S)
        if m:
            try:
                data = json.loads(m.group(0))
                return data if isinstance(data, list) else []
            except json.JSONDecodeError:
                return []
        return []
```

注意：`_call_llm_with_retry` 的 `response_format={"type": "json_object"}` 可能因 provider 报错——若实验发现 provider 不支持，可改传 `None`。步骤 4 验证时留意。

- [ ] **Step 4: 运行测试确认通过**

Run: `docker compose --profile test run --rm test uv run pytest backend/tests/services/clustering/experiments/test_memory_labels.py -q`
Expected: PASS（6 passed）

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/clustering/experiments/prompts.py backend/app/services/clustering/experiments/memory_labels.py backend/tests/services/clustering/experiments/test_memory_labels.py
git commit -m "feat(experiments): LLM cluster label summary generation with fallback"
```

---

### Task 4: 孤岛题增量分配（LLM）

**Files:**
- Modify: `backend/app/services/clustering/experiments/memory_labels.py`
- Test: `backend/tests/services/clustering/experiments/test_memory_labels.py`

- [ ] **Step 1: 写失败测试**

```python
def test_assign_singletons_llm_decides(monkeypatch, test_db):
    _seed_db(test_db)
    from app.services.clustering.experiments.memory_labels import (
        load_cluster_data, assign_singletons,
    )

    calls = {"n": 0}

    async def fake_llm(prompt, system_msg, response_format, user_id, model):
        calls["n"] += 1
        return json.dumps({"match": 1, "reason": "同一道限流题"}, ensure_ascii=False)

    monkeypatch.setattr(
        "app.services.clustering.experiments.memory_labels._call_llm_with_retry",
        fake_llm,
    )
    clusters, singletons = load_cluster_data(test_db)
    labels = {1: "高并发限流", 2: "Java 线程池"}
    results = assign_singletons(singletons, clusters, labels, user_id=None)

    # id=3 的孤岛被分到 cluster 1
    assert results[3]["match"] == 1
    assert calls["n"] == 1


def test_assign_singletons_respects_no_match(monkeypatch, test_db):
    _seed_db(test_db)
    from app.services.clustering.experiments.memory_labels import (
        load_cluster_data, assign_singletons,
    )

    async def fake_llm(prompt, system_msg, response_format, user_id, model):
        return json.dumps({"match": None, "reason": "新主题"}, ensure_ascii=False)

    monkeypatch.setattr(
        "app.services.clustering.experiments.memory_labels._call_llm_with_retry",
        fake_llm,
    )
    clusters, singletons = load_cluster_data(test_db)
    labels = {1: "高并发限流", 2: "Java 线程池"}
    results = assign_singletons(singletons, clusters, labels, user_id=None)

    assert results[3]["match"] is None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `docker compose --profile test run --rm test uv run pytest backend/tests/services/clustering/experiments/test_memory_labels.py::test_assign_singletons_llm_decides -q`
Expected: FAIL（ImportError: cannot import name 'assign_singletons'）

- [ ] **Step 3: 实现 assign_singletons**

在 `memory_labels.py` 追加：

```python
from app.services.clustering.experiments.prompts import SINGLETON_ASSIGN_PROMPT

ASSIGN_BATCH_SIZE = 20


async def assign_singletons(
    singletons: list[dict],
    clusters: list[dict],
    labels: dict[int, str],
    user_id: int | None,
) -> dict[int, dict]:
    """孤岛题增量分配：LLM 判断归属已有 cluster / 独立新题。

    Args:
        labels: {cluster_qb_id: label}（Task 3 产物）
    Returns: {singleton_qb_id: {"match": cluster_qb_id | None, "reason": str}}
    """
    # 先做文本预筛，命中直接确定性分配（零 LLM 成本）
    results: dict[int, dict] = {}
    pre = text_prefilter(singletons, clusters)
    for s in singletons:
        if s["qb_id"] in pre:
            results[s["qb_id"]] = {"match": pre[s["qb_id"]], "reason": "文本精确匹配"}

    remaining = [s for s in singletons if s["qb_id"] not in results]
    label_lines = "\n".join(f"{qid} | {label}" for qid, label in labels.items())
    if not label_lines:
        label_lines = "\n".join(f"{c['qb_id']} | {c['question'][:40]}" for c in clusters)

    for i in range(0, len(remaining), ASSIGN_BATCH_SIZE):
        batch = remaining[i : i + ASSIGN_BATCH_SIZE]
        for s in batch:
            prompt = SINGLETON_ASSIGN_PROMPT.format(
                qb_id="{qb_id}",
            )
            prompt = (
                f"【已有聚类标签】\n{label_lines}\n\n"
                f"【新题目】\n{s['qb_id']} | {s['question']}\n\n"
                + prompt
            )
            try:
                raw = await _call_llm_with_retry(
                    prompt,
                    system_msg="你是一个面试题去重专家。",
                    response_format={"type": "json_object"},
                    user_id=user_id,
                )
                data = _extract_json_object(raw)
                m = data.get("match")
                results[s["qb_id"]] = {
                    "match": int(m) if m is not None else None,
                    "reason": str(data.get("reason", ""))[:200],
                }
            except Exception as e:
                logger.warning(f"[experiment] 增量分配失败 qb_id={s['qb_id']}: {e}")
                results[s["qb_id"]] = {"match": None, "reason": f"LLM 调用失败: {e}"[:200]}
    return results


def _extract_json_object(raw: str) -> dict:
    """从 LLM 输出提取 JSON 对象（容忍 markdown 代码块包裹）"""
    import re

    text = (raw or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            try:
                data = json.loads(m.group(0))
                return data if isinstance(data, dict) else {}
            except json.JSONDecodeError:
                return {}
        return {}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `docker compose --profile test run --rm test uv run pytest backend/tests/services/clustering/experiments/test_memory_labels.py -q`
Expected: PASS（8 passed）

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/clustering/experiments/memory_labels.py backend/tests/services/clustering/experiments/test_memory_labels.py
git commit -m "feat(experiments): LLM singleton-to-cluster assignment with prefilter"
```

---

### Task 5: 评估脚本（全流程 + Markdown 报告）

**Files:**
- Create: `backend/app/services/clustering/experiments/evaluate.py`
- Modify: `.gitignore`

- [ ] **Step 1: 实现 evaluate.py**

Create `backend/app/services/clustering/experiments/evaluate.py`:

```python
"""聚类实验评估入口：生产数据全流程 + Markdown 报告。

运行：docker compose run --rm backend python -m app.services.clustering.experiments.evaluate [--round N]
输出：backend/experiment_reports/round<N>.md
"""
import argparse
import asyncio
import logging
import os
import time

from app.db.connection import get_db_connection

logging.basicConfig(level=logging.INFO)

REPORT_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "experiment_reports")


async def main(round_no: int):
    os.makedirs(REPORT_DIR, exist_ok=True)
    conn = get_db_connection()
    t0 = time.monotonic()

    from app.services.clustering.experiments.memory_labels import (
        load_cluster_data,
        generate_cluster_labels,
        assign_singletons,
        text_prefilter,
    )

    clusters, singletons = load_cluster_data(conn)
    stats = {
        "total_qb": len(clusters) + len(singletons),
        "known_clusters": len(clusters),
        "singletons": len(singletons),
    }

    # 1) 文本预筛（零成本确定性分配）
    pre_matches = text_prefilter(singletons, clusters)

    # 2) 标签摘要生成
    labels = await generate_cluster_labels(clusters, user_id=None)
    label_failback = sum(1 for c in clusters if labels.get(c["qb_id"]) == c["question"][:40])

    # 3) LLM 增量分配（跳过已被文本预筛命中的）
    results = await assign_singletons(singletons, clusters, labels, user_id=None)

    llm_assign = {
        qid: r for qid, r in results.items()
        if qid not in pre_matches and r["match"] is not None
    }
    new_island = {
        qid: r for qid, r in results.items() if r["match"] is None
    }

    elapsed = time.monotonic() - t0
    _write_report(round_no, conn, stats, pre_matches, labels, results, llm_assign, new_island, elapsed)
    print(f"[experiment] 完成: 已知cluster={stats['known_clusters']} 孤岛={stats['singletons']} "
          f"确定性合并={len(pre_matches)} LLM合并={len(llm_assign)} 维持孤岛={len(new_island)} "
          f"耗时={elapsed:.1f}s -> {REPORT_DIR}/round{round_no}.md")


def _write_report(round_no, conn, stats, pre_matches, labels, results, llm_assign, new_island, elapsed):
    lines = [
        f"# 聚类实验报告 round {round_no}",
        "",
        f"**时间**: {time.strftime('%Y-%m-%d %H:%M:%S')}  **耗时**: {elapsed:.1f}s",
        "",
        "## 数据概览",
        "",
        f"- 题库总数: {stats['total_qb']}",
        f"- 已知聚类（frequency>1）: {stats['known_clusters']}",
        f"- 孤岛题（frequency=1）: {stats['singletons']}",
        "",
        "## 分配结果",
        "",
        f"- 文本预筛确定性合并: **{len(pre_matches)}**",
        f"- LLM 判断合并到已有聚类: **{len(llm_assign)}**",
        f"- 维持独立新题: **{len(new_island)}**",
        f"- 孤岛率变化: {stats['singletons']} → {len(new_island)}（-{(1 - len(new_island) / max(stats['singletons'], 1)) * 100:.1f}%）",
        "",
        "## 抽样核验（LLM 合并前 25 条）",
        "",
    ]
    for i, (qid, r) in enumerate(sorted(llm_assign.items(), key=lambda kv: kv[0])[:25], 1):
        target = _q_by_id(conn, r["match"])
        src = _q_by_id(conn, qid)
        lines += [
            f"### {i}. 孤岛题 {qid} → 聚类 {r['match']}",
            f"- 孤岛题: {src}",
            f"- 目标代表题: {target}",
            f"- 原因: {r['reason']}",
            "",
        ]
    lines += ["## 标签摘要样本（前 10 个聚类）", ""]
    for cid, label in sorted(labels.items())[:10]:
        lines.append(f"- cluster {cid}: {label}")
    lines.append("")
    lines += ["## 成本估算", ""]
    lines += [
        f"- 标签摘要 LLM 调用: {max(1, (stats['known_clusters'] + 19) // 20)} 次",
        f"- 增量分配 LLM 调用: {sum(1 for qid in results if qid not in pre_matches)} 次",
        f"- 摘要回退代表题（LLM 失败）: {label_failback} 个",
        "",
    ]
    path = os.path.join(REPORT_DIR, f"round{round_no}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"[experiment] 报告已写入 {path}")


def _q_by_id(conn, qid: int) -> str:
    row = conn.execute("SELECT question FROM question_bank WHERE id = ?", (qid,)).fetchone()
    return row["question"] if row else f"(缺失 {qid})"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--round", type=int, default=1)
    args = parser.parse_args()
    asyncio.run(main(args.round))
```

- [ ] **Step 2: 语法验证**

Run: `docker compose --profile test run --rm test uv run python -m py_compile backend/app/services/clustering/experiments/evaluate.py backend/app/services/clustering/experiments/memory_labels.py`
Expected: 无输出（编译成功）

- [ ] **Step 3: 追加 .gitignore**

在 `.gitignore` 末尾追加：

```
backend/experiment_reports/
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/clustering/experiments/evaluate.py .gitignore
git commit -m "feat(experiments): evaluation runner with markdown report"
```

---

### Task 6: 第一轮实验运行 + 人工核验

**Files:** 无代码变更（运行 + 核验 + 记录）

- [ ] **Step 1: 确认生产 DB 可访问、LLM 配置有效**

Run: `docker compose run --rm backend python -c "from app.core.config import _reload_from_db; _reload_from_db(); from app.services.llm import raw_llm_call; import asyncio; print(asyncio.run(raw_llm_call(user_id=None, model='', messages=[{'role':'user','content':'ping'}], max_tokens=5)))"`
Expected: 输出 LLM 回复（确认 key/模型可用）

- [ ] **Step 2: 运行第一轮实验**

Run: `docker compose run --rm backend python -m app.services.clustering.experiments.evaluate --round 1`
Expected: 输出统计行 + `backend/experiment_reports/round1.md` 生成

- [ ] **Step 3: 核验报告（用户参与）**

用户阅读 `backend/experiment_reports/round1.md`，重点核验"抽样核验"25 条合并是否语义合理。判断标准：
- 合并对考察点相同 → 合理（效果提升）
- 明显无关的误合并 → 需要收紧 prompt（回 Task 3/4 调 prompt 后重跑 round 2）
- 该合并未合并 → 需要放宽判断标准

- [ ] **Step 4: 迭代调参（按核验结果）**

若误合并多 → 强化 `SINGLETON_ASSIGN_PROMPT` 的"不合并"约束（如加"宁可漏合并不可错合并"）；若漏合并多 → 放宽。修改后重跑 round 2：
Run: `docker compose run --rm backend python -m app.services.clustering.experiments.evaluate --round 2`

- [ ] **Step 5: 结论与决策（用户拍板）**

对比报告与现有方案（现状：孤岛 187 题保持孤岛；文本预筛 + LLM 标签分配的新算法合并数 M）。用户判定"效果好了"后，再单独 brainstorming 并入生产（替代 matcher 候选池或作为新匹配层）。

---

## Self-Review

**Spec 覆盖检查：**
- ✅ 生产数据量化对比：Task 1（加载器）→ Task 5（评估脚本）→ Task 6（运行）
- ✅ 标签摘要记忆方案（LLM-MemCluster 模式）：Task 3（摘要生成）+ Task 4（增量分配）
- ✅ 独立代码不碰生产：experiments/ 独立包，仅复用 `_call_llm_with_retry` / `_normalize_question_text` 只读接口
- ✅ 多轮实验：Task 6 Step 4 支持 round N 重跑
- ✅ 人工核验入口：Task 6 Step 3（报告抽样 25 条）
- ✅ 成本统计：Task 5 报告含 LLM 调用次数

**Placeholder 扫描：** 无 TBD/TODO；所有函数签名、导入路径在任务间一致（`load_cluster_data` / `text_prefilter` / `generate_cluster_labels` / `assign_singletons` / `_extract_json_array` / `_extract_json_object`）。

**Type 一致性：** `generate_cluster_labels` 返回 `dict[int, str]`（labels），`assign_singletons` 消费同型 labels；`text_prefilter` 返回 `dict[int, int]`，`assign_singletons` 内部复用；Task 4 测试与 Task 3 签名一致。

**风险提示（实现时验证）：**
- `_call_llm_with_retry(response_format={"type": "json_object"})` 若 provider 不支持，改为 `response_format=None` 并依赖 `_extract_json_array/_extract_json_object` 容错解析
- 生产 DB 通过 `docker compose run` 访问是只读操作，不写库
- 实验 LLM 调用约 10-20 次，成本可控；若摘要批量失败，回退机制保证不中断
