# 八股刷题模块深度修复 Spec

> 基于 tech-audit 深度审计发现，参考 Anki/FSRS、LeetCode、GitHub Contribution Graph 等产品的最佳实践。

---

## 背景与最佳实践参考

| 问题 | 最佳实践来源 | 核心原则 |
|------|-------------|----------|
| 时区不一致 (F1/F6) | FSRS/Anki、GitHub Contribution Graph、LeetCode Streak | **Server-authoritative today**：服务端返回 study_date，前端所有今天判断统一用此字段 |
| 进度条漂移 (F2) | FSRS review sync、Memdora SRS | **Single source of truth**：进度数字只由服务端计算，前端做最小乐观更新 |
| 双重确认 (F3) | shadcn-vue Dialog、Radix UI Alert | **Single confirmation**：只用一个 styled dialog，不用 window.confirm |
| 模式切换跳题单 (F4) | LeetCode 题单内模式切换 | **Mode ≠ Scope**：刷题模式是视图模式，不应改变当前题单 |
| N+1 查询 (F5) | SQLite CTE/conditional aggregation | **Single aggregation query**：用 GROUP BY 替代循环 |
| 预测时区 (F6) | 同 F1 | **Consistent timezone**：forecast 和 review metrics 用同一时区基准 |

---

## 修复 F1：后端返回 study_date，前端统一使用

### 原理

GitHub Contribution Graph、LeetCode Streak 等产品的标准做法：服务端在每个依赖今天的响应中返回当前学习日日期（字符串 YYYY-MM-DD），前端用此字段替代 new Date() 做所有今天判断。

### 后端修改

**文件**：backend/app/services/practice_deck_service.py

1. _study_day_utc_bounds 保持不变（仍用于 SQL 查询）

2. 新增辅助函数返回学习日日期字符串：

```python
def _study_date_string(now: datetime | None = None) -> str:
    """Return the current learner-facing calendar day as YYYY-MM-DD."""
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    zone = _study_timezone()
    return current.astimezone(zone).date().isoformat()
```

3. list_deck_questions 的 due 分支，在 deck dict 中追加 study_date

4. GET /api/practice/decks 返回的每个 deck summary 中也追加 study_date

### 前端修改

**文件**：frontend/src/composables/usePracticeDecks.js

5. isStudyDayToday(value) 改为接受 studyDate 参数，用后端返回的 study_date 做比较

6. applyQuestionResponse 中传入 studyDate

7. submitReview 和 correctReview 中的 wasPassedToday 用 studyDate

---

## 修复 F2：修正自评时进度条数字一致性

### 原理

FSRS review sync 的标准做法：进度数字只由服务端计算并返回，前端做最小乐观更新。

### 问题

again→good 修正时 remaining_today 被错误递减为负数，导致进度条跳到 100%。

### 修复

**文件**：frontend/src/composables/usePracticeDecks.js

correctReview 中 wasPassedToday !== passedNow 分支，增加 relearning_count 调整：

```javascript
if (wasPassedToday !== passedNow) {
  const delta = passedNow ? 1 : -1
  reviewedDeck.completed_today = Math.max(0, Number(reviewedDeck.completed_today || 0) + delta)
  reviewedDeck.remaining_today = Math.max(0, Number(reviewedDeck.remaining_today || 0) - delta)
  reviewedDeck.relearning_count = Math.max(0, Number(reviewedDeck.relearning_count || 0) - delta)
  reviewedDeck.planned_today = Number(reviewedDeck.completed_today || 0) + Number(reviewedDeck.remaining_today || 0)
}
```

---

## 修复 F3：删除题单单一确认弹窗

**文件**：frontend/src/views/PracticeDecksView.vue

deleteManagerDeck 中删除 window.confirm，直接调用 deleteDeck（内部已有 styled confirm）

**文件**：frontend/src/components/SiteHeader.vue

coding 题单删除同样删除 window.confirm

---

## 修复 F4：模式切换不改变当前题单

**文件**：frontend/src/components/business/PracticeMode.vue

switchToQuiz 不再 emit select-deck('due')，只改 viewMode
switchToBrowse 不再 emit select-deck('all')，只改 viewMode

---

## 修复 F5：list_decks N+1 查询优化

**文件**：backend/app/services/practice_deck_service.py

list_decks 中缓存 _base_query_parts 结果，避免重复调用 build_bank_where_clause

---

## 修复 F6：forecast 使用 study timezone

**文件**：backend/app/services/practice_deck_service.py

review_forecast 的日期计算改为使用 study timezone 而非 UTC

---

## 修复 F7：_study_streak 优化

**文件**：backend/app/services/practice_deck_service.py

_study_streak 查询加时间范围限制（400天），避免全表扫描

---

## 修改清单

| # | 文件 | 修改内容 | 优先级 |
|---|------|---------|--------|
| 1 | practice_deck_service.py | 新增 _study_date_string() | 🔴 |
| 2 | practice_deck_service.py | list_deck_questions 返回 study_date | 🔴 |
| 3 | practice.py | list_decks 返回 study_date | 🔴 |
| 4-7 | usePracticeDecks.js | isStudyDayToday 用 studyDate 参数 | 🔴 |
| 8 | usePracticeDecks.js | correctReview 进度条平衡修复 | 🔴 |
| 9-10 | PracticeDecksView/SiteHeader | 删除 window.confirm | 🟡 |
| 11-12 | PracticeMode.vue | switchToQuiz/Browse 不切换题单 | 🟡 |
| 13 | practice_deck_service.py | _study_streak 加时间范围 | 🟢 |
| 14 | practice_deck_service.py | forecast 用 study timezone | 🟡 |
| 15 | practice_deck_service.py | list_decks 缓存查询 | 🟢 |

---

## 验证方案

### 后端测试
```bash
docker compose --profile test run --rm test uv run pytest backend/tests/services/test_practice_api.py -q -v
docker compose --profile test run --rm test uv run pytest backend/tests/services/test_practice_scheduler.py -q -v
docker compose --profile test run --rm test uv run pytest backend/tests/services/test_practice_due_queue.py -q -v
```

### 前端测试
```bash
cd frontend && npm run build
cd frontend && npm run test
```

### 手动验证
1. 时区测试：验证刷题进度与 Asia/Shanghai 一致
2. 修正测试：again→good 修正后进度条不跳到 100%
3. 删除测试：删除题单只弹一次确认框
4. 模式切换测试：自定义题单内切换模式不跳题
