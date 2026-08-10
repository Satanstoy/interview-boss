# 今日复习调度系统改造 — 机会脉冲模型 + 已掌握题抽查

日期：2026-08-06
状态：设计完成，待实现
决策依据：`docs/analysis/2026-08-06-today-review-scheduler-decisions.md`（含全部实验数据）

## 背景

第一阶段已交付：due「今日复习」队列 + 风险排序 + 单批次里程碑紧迫度 + 用户招聘偏好 API。审查发现三个结构性缺陷：

1. **单批次快照**：`get_milestones(year, batch)` 只生成所选批次的里程碑，秋招结束后紧迫度永久归零，用户必须手动改批次才能进入春招——违背"秋招→春招→社招连续"的现实
2. **伪 DDL**：window_close 的 deadline 压缩（Anki exam mode 思路）在无真实截止日（补录/春招/社招接着来）的求职场景是过度设计
3. **学完即空虚**：题库仅 321 道，SM-2-lite 间隔拉长后 73% 的天复习量 < 5 题——"没题可刷"比任何参数更伤留存

本 spec 落地第二阶段：**机会脉冲紧迫度模型（无 DDL）+ 届次时间线自动流转 + 用户节奏档位 + 已掌握题 30 天循环抽查**。

## 目标

1. 紧迫度 = 机会脉冲（base 0.2 + 窗口脉冲 + 节奏偏移），全年连续、无归零、批次自动流转
2. 删除 deadline 参数与压缩逻辑（连带简化 record_review/_user_urgency）
3. 已掌握题（state='mastered'）进入 30 天循环抽查，again 降级回炉
4. 设置页：届次为主 + 节奏 3 档，批次自动跟随展示
5. 状态行：显示当前机会窗口 + 下一窗口

## 决策参数（实验定稿）

| 参数 | 值 | 来源 |
|---|---|---|
| base | 0.2 | 全年曲线实验（0.15 太弱 / 0.3 全年无低压） |
| amp（全局振幅系数） | 0.6 | 实验（0.5 峰值 0.7 冲刺感弱 / 0.7 峰值 0.9 过激） |
| 窗口半宽 | 45 天 | 实验（30 突变 / 60 高压期过长） |
| 窗口相对权重 | 秋招正式批 1.00 / 春招主批 0.83 / 暑期实习 0.67 / 提前批 0.50 | 机会密度 |
| 节奏偏移 | 轻松 −0.3 / 标准 0 / 冲刺 +0.3 | 决策报告 §4 |
| 抽查周期 | **固定 30 天**（easy/good/hard 统一），again 降级 | 周期实验（分级方案回炉率 8-16%，固定 30 天 0.6%） |
| urgency 间隔缩放 | ×(1 − 0.4×urgency)，again 不受调制 | 第一阶段已定，保留 |
| 容量分配 | 新题预算 = max(0, 容量 − due复习 − 抽查) | Anki 杠杆原则 |

## 算法规格

### 1. 机会脉冲紧迫度（重写 `recruitment_milestones.py`）

```python
@dataclass(frozen=True)
class OpportunityWindow:
    name: str          # '暑期实习' | '提前批' | '秋招正式批' | '春招主批'
    peak: date
    weight: float      # 相对权重 0.50~1.00

def get_season_windows(graduation_year: int) -> list[OpportunityWindow]:
    """2027 届 → 4 个窗口（跨 N-1 春 到 N 年春）"""
    # 暑期实习   peak=N-1-03-15 w=0.67
    # 提前批     peak=N-1-08-15 w=0.50
    # 秋招正式批 peak=N-1-10-15 w=1.00
    # 春招主批   peak=N-04-15    w=0.83

def compute_urgency(windows, today, pace: str = 'standard') -> dict:
    """
    base = 0.2（社招/日常实习随时可能面试）
    pulse(w) = weight * AMP * (1 - |today - peak| / HALF_WIDTH)  当 |days| <= 45
    紧迫度 = clamp(base + Σ pulse + pace_offset, 0, 1)
    返回 {urgency, current_window, next_window}
      current_window: 当前处于脉冲非零的窗口（重叠时取权重最大的）
      next_window:    下一个未来窗口（peak > today），供状态行展示
    """
```

- 无届次/日常实习/毕业 → `windows=[]` → urgency = base 恒 0.2（社招节奏）
- 旧 `get_milestones(graduation_year, batch)` / `Milestone` 类型删除；`compute_urgency` 签名变更（旧调用方全量更新）

### 2. 调度器（`practice_scheduler.py`）

```python
def schedule_review(current, rating, *, now=None, urgency=0.0) -> ScheduledReview:
    """删除 deadline 参数与压缩逻辑"""
    # 新增 mastered 抽查分支（置于 again 判断之前）：
    if current.state == 'mastered' and rating != 'again':
        interval_days = 30.0          # 固定 30 天循环（实验定稿）
        proficiency = min(5, proficiency + (0 if rating in ('hard',) else 1 if rating == 'good' else 2))
        state = 'mastered'
        return ...                     # ease_factor 不变
    # again 走既有分支：proficiency-1、0.02 天 → 自然回炉（state 变 relearning）
```

要点：**回炉是免费的**——again 分支已实现 proficiency-1 + 29 分钟 + state='relearning'，抽查的 again 直接命中。

### 3. 队列（`practice_deck_service.py`）

due 条件不变（`next_review_at IS NULL OR <= now`），抽查题天然命中。改动：

```sql
-- 排序升级：due 复习 → 抽查（保持手感）→ 新题 → 未来
CASE WHEN uqr.next_review_at IS NULL THEN 2
     WHEN uqr.state = 'mastered' AND datetime(uqr.next_review_at) <= datetime('now') THEN 1
     WHEN datetime(uqr.next_review_at) <= datetime('now') THEN 0
     ELSE 3 END
-- 抽查桶内按 frequency DESC（保持重要手感），新题桶内按 frequency DESC（已有）
```

- `_normalise_question` 增加 `is_checkin = (state == 'mastered')`
- **max_new 改为后端自动计算**：`list_deck_questions`（due 题单）内读 `user_recruitment_pref.daily_capacity`，预算 = max(0, 容量 − 到期复习数 − 抽查数)，不再依赖前端传参（参数保留作覆盖）
- due 计数（list_decks）：不变（抽查已含在 `next_review_at <= now` 口径内）

### 4. 数据模型（migration 063）

```sql
ALTER TABLE user_recruitment_pref ADD COLUMN pace TEXT NOT NULL DEFAULT 'standard';
-- 语义变更：batch 字段降级为展示标签（不再参与调度），新写入默认 ''
```

### 5. API 契约

**GET/PUT `/api/profile/recruitment`**（`profile.py`）：

```json
{
  "graduation_year": 2027,          // 届次（算法唯一输入）
  "batch": "autumn",                // 兼容字段，仅展示
  "daily_capacity": 30,
  "pace": "standard",               // 新增：easy/standard/hard
  "urgency": 0.43,
  "windows": [{"name": "秋招正式批", "peak": "2026-10-15", "weight": 1.0}],   // 全年窗口（替代 milestones）
  "current_window": "提前批",        // 当前脉冲窗口（可空）
  "next_window": "秋招正式批"        // 下一窗口（可空）
}
```

PUT 校验：pace ∈ {easy, standard, hard}；`compute_urgency` 结果随 PUT 响应返回（保持时间线刷新契约）。

**`POST /api/practice/review`**：响应不变；`record_review` 内部对 mastered 卡走 30 天分支。`evaluate-answer` 同。

**`GET /api/practice/decks/due/questions`**：item 增加 `is_checkin` 字段。

### 6. 前端

| 文件 | 改动 |
|---|---|
| `PracticeView.vue` | 状态行重构：`当前窗口「提前批」· 距「秋招正式批」高峰 65 天 · 冲刺中 · 容量 30`；无窗口 → 「持续准备中」 |
| `SettingsInterview.vue` | 批次下拉 → 节奏 3 档单选（轻松/标准/冲刺）+ 届次 + 容量；时间线预览改为全年窗口列表（当前高亮） |
| `PracticeMode.vue` | 抽查题卡显示「保持手感」徽标（is_checkin）；空态文案不变 |
| `usePracticeDecks.js` | 无结构性改动（抽查由后端混入队列） |

## 边界情况

| 场景 | 行为 |
|---|---|
| 未设置届次（社招） | windows=[] → urgency=0.2 恒定；状态行「持续准备中」 |
| 毕业 3 个月后 | 届次保留但窗口全过期 → 退化为 0.2（社招节奏），不报错 |
| 已掌握题再次复习 30 天后仍未动 | next_review_at <= now 持续命中抽查队列，每天 ≤1 道 |
| 抽查 again | proficiency 4 + 29 分钟 → 回炉密集复习；风险权重 (5−4)=1 自动提升 |
| 容量极小（5）且 due 满 | 新题预算 0、抽查 0——复习优先，符合"复习永不截断" |
| 老数据 batch 有值 | 兼容：仅展示，算法忽略 |

## 测试计划

| 域 | 用例 |
|---|---|
| `test_recruitment_milestones`（重写） | 4 窗口生成（届次偏移正确）；紧迫度：窗口内三角爬升/衰减、多窗口叠加、base 下限、pace 三档偏移、全过期退化 0.2、无届次 0.2 |
| `test_practice_scheduler`（改） | 删 deadline 用例；mastered+good → 30 天重置；mastered+easy → 30 天 + proficiency 7 钳制；mastered+again → 降级回炉（0.02 天 + relearning）；urgency 缩放仍作用于 30 天？—— **否**，抽查恒定 30 天（实验定稿），普通复习照旧缩放 |
| `test_practice_due_queue`（改） | 抽查桶在 due 后新题前；is_checkin 标记；max_new 自动预算（容量 30，due 10 + 抽查 5 → 新题 15）；容量被占满 → 新题 0 |
| `test_recruitment_pref_api`（改） | pace 读写 + 校验；windows/current_window/next_window 返回 |
| `test_review_urgency_wiring`（改） | 删 deadline 断言；urgency 透传不变 |
| 前端 `today-review.spec.js`（改） | 状态行新文案；抽查徽标；节奏档位保存 |
| 新增抽查 E2E | mastered 题出现在队列 + 徽标 + 复习后 30 天消失 |

## 实施任务划分（供 writing-plans 展开）

1. `recruitment_milestones.py` 重写（窗口 + 新 compute_urgency）＋测试重写
2. `practice_scheduler.py`（删 deadline + mastered 30 天分支）＋测试
3. migration 063（pace 字段）
4. `profile.py` API（pace + windows 契约）＋测试
5. `practice_deck_service.py`（抽查桶排序 + is_checkin + 自动 max_new）＋测试
6. `practice.py`/`practice_review_service.py` 接线（删 deadline 链）＋测试
7. 后端全量回归
8. 前端状态行 + 设置页节奏档位 + 徽标
9. 前端测试更新 + 新增抽查 E2E
10. 文档（CLAUDE.md 系列 + 决策报告附录）
