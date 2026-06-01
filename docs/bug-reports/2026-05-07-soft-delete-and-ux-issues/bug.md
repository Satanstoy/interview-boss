# Bug 详细分析报告

**Bug ID:** BUG-001 ~ BUG-005
**发现日期:** 2026-05-07
**状态:** 已确认

## 问题概述

本次审计发现 5 个问题，涉及数据安全（硬删除风险）、用户体验（导入流程缺陷）、数据质量（脏数据）和功能完整性（LLM 配置修改）。

---

## BUG-001: question_bank 批量删除使用硬删除

- **位置:** `backend/app/routers/master_bank.py:805-888`
- **症状:** 题库题目被删除后永久丢失，无法通过回收站恢复
- **根因:** `question_bank` 表没有 `deleted_at` 字段，删除操作使用 `DELETE FROM` 物理删除
- **影响:** 数据误删后无法恢复，与 jd/interview/questions_detail 表的软删除策略不一致
- **严重程度:** P0 (Critical)

**涉及代码:**

1. 单条删除 `DELETE /api/master-bank/{question_id}` (第 805-839 行):
```python
cursor.execute("DELETE FROM questions_detail WHERE question = ?", (question_text,))
cursor.execute("DELETE FROM user_question_view WHERE question_bank_id = ?", (question_id,))
cursor.execute("DELETE FROM question_position WHERE question_id = ?", (question_id,))
cursor.execute("DELETE FROM question_bank WHERE id = ?", (question_id,))
cursor.execute("DELETE FROM user_practice_history WHERE question_bank_id = ?", (question_id,))
```

2. 批量删除 `POST /api/master-bank/batch-delete` (第 842-888 行):
```python
cursor.execute(f"DELETE FROM questions_detail WHERE question IN ({qph})", question_texts)
cursor.execute(f"DELETE FROM user_question_view WHERE question_bank_id IN ({ph2})", found_ids)
cursor.execute(f"DELETE FROM question_position WHERE question_id IN ({ph2})", found_ids)
cursor.execute(f"DELETE FROM question_bank WHERE id IN ({ph2})", found_ids)
cursor.execute(f"DELETE FROM user_practice_history WHERE question_bank_id IN ({ph2})", found_ids)
```

3. 题库重建 `POST /api/master-bank/build` (第 314-328 行):
```python
cursor.execute("DELETE FROM question_bank WHERE job_position = ? AND owner_id IS NULL", (position,))
```

---

## BUG-002: 前端导入缺少类型选择和招聘季节选择

- **位置:** `frontend/src/components/StagingPanel.vue:1-225`
- **症状:** 用户导入数据时无法选择类型（JD/面经）和招聘季节
- **根因:** 组件未提供类型选择和季节选择的 UI 控件
- **影响:** 类型完全依赖后端 AI 解析，可能不准确；季节取全局设置，不灵活
- **严重程度:** P1 (High)

**当前实现:**
- 类型: 由后端 AI 自动判断，前端只展示结果
- 季节: 取自 `props.activeSeason`，未设置时默认 `'2027届暑期实习'`

**期望实现:**
- 提供 JD/面经类型选择（可选"自动识别"）
- 提供招聘季节下拉选择（从已有季节列表中选择或新增）

---

## BUG-003: job_positions 表存在脏数据

- **位置:** `job_positions` 表
- **症状:** 用户设置中的"目标岗位"下拉列表显示测试数据
- **根因:** 之前测试留下的脏数据未清理
- **影响:** 用户界面显示混乱，影响岗位选择体验
- **严重程度:** P2 (Medium)

**脏数据列表:**
```
AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
test@#$%!
测试岗位ABC
测试开发
```

**清理方案:**
1. 删除无效岗位记录
2. 清理关联的 `question_position` 记录
3. 清理关联的 `taxonomy` 记录

---

## BUG-004: question_bank 表 cat1 字段存在脏数据

- **位置:** `question_bank` 表
- **症状:** 题库分类筛选中出现 `test` 等测试分类
- **根因:** 测试数据未清理
- **影响:** 分类筛选结果不准确
- **严重程度:** P2 (Medium)

**脏数据:**
```
test
```

**清理方案:**
将 `cat1 = 'test'` 的记录更新为有效分类或清空。

---

## BUG-005: 用户个人 LLM 配置修改问题

- **位置:** `frontend/src/components/SettingsPanel.vue:264-331` 和 `backend/app/routers/profile.py:135-193`
- **症状:** 用户反馈个人 LLM 配置保存后无法修改
- **根因:** 经代码审查，API 和前端逻辑均支持修改。可能原因：
  1. 前端 `loadMyLLM()` 调用后状态更新不及时
  2. API 返回的 `configured` 状态可能影响前端显示
  3. 用户操作流程不清晰（需要点击"修改配置"按钮进入编辑模式）
- **影响:** 用户无法更新 LLM 配置
- **严重程度:** P1 (High)

**代码流程分析:**

1. 前端加载配置 (`loadMyLLM`):
```javascript
const data = await fetchMyLLMConfig()
myLLM.configured = data.configured
if (data.configured) {
  myLLM.settings = data.settings
}
myLLM.editing = false  // 保存后关闭编辑模式
```

2. 前端保存配置 (`saveMyLLM`):
```javascript
await updateMyLLMConfig(payload)
toast.success('LLM 配置已保存')
await loadMyLLM()  // 重新加载配置
```

3. API 更新逻辑 (`update_my_llm_config`):
```python
conn.execute(
    "INSERT INTO user_llm_config ... ON CONFLICT(user_id) DO UPDATE SET ...",
    (user['id'], final_key, base_url, model, timeout)
)
```

**问题定位:** 代码逻辑正确，问题可能是用户体验层面：
- 用户可能不知道需要点击"修改配置"按钮才能进入编辑模式
- 或者保存后界面没有正确刷新显示最新状态

---

## 复现步骤

### BUG-001 复现步骤:
1. 登录管理员账户
2. 进入"高频题库"页面
3. 选择任意题目，点击删除
4. 删除成功后，无法在回收站中找到该题目

### BUG-002 复现步骤:
1. 登录任意账户
2. 进入"导入"页面
3. 粘贴一段 JD 文本
4. 观察：无法选择"这是 JD"或"这是面经"
5. 观察：无法选择招聘季节

### BUG-003 复现步骤:
1. 登录任意账户
2. 进入"设置"页面
3. 查看"目标岗位"下拉列表
4. 观察：显示 `AAAAAAAAAAA...`、`test@#$%!` 等无效数据

### BUG-005 复现步骤:
1. 登录普通用户账户
2. 进入"设置"页面
3. 配置 LLM 设置并保存
4. 尝试再次修改 LLM 配置
5. 观察：需要点击"修改配置"按钮才能进入编辑模式

---

## 修复建议

### BUG-001 修复方案:
1. 为 `question_bank` 表添加 `deleted_at` 字段
2. 将所有删除操作改为软删除（设置 `deleted_at`）
3. 添加回收站查询和恢复接口
4. 级联软删除关联表记录

### BUG-002 修复方案:
1. 在 `StagingPanel.vue` 中添加类型选择（JD/面经/自动识别）
2. 添加招聘季节下拉选择（从已有季节列表中选择或新增）
3. 修改 `submitAll` 函数，将选择的类型和季节传给后端

### BUG-003/004 修复方案:
1. 编写 SQL 脚本清理脏数据
2. 添加数据验证，防止无效数据写入

### BUG-005 修复方案:
1. 优化前端用户体验，使"修改配置"按钮更加明显
2. 确保保存后界面正确刷新
3. 考虑直接进入编辑模式而非显示摘要
