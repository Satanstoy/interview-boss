# Bug 详细分析报告

**日期:** 2026-05-07
**状态:** 已确认

---

## BUG-001: 前端类型选择字段名不匹配（P1）

- **位置:** `frontend/src/components/StagingPanel.vue:235` vs `backend/app/routers/submit.py:247`
- **症状:** 导入界面选择"JD"或"面经"后，后端仍使用 LLM 自动识别
- **根因:** 前端 `formData.append('type', importType.value)` 发送 `type`，后端 `content_type: Optional[str] = Form("")` 期望 `content_type`
- **影响:** 用户无法指定导入类型，始终走 SYSTEM_PROMPT（LLM 自动判断）
- **严重程度:** P1

---

## BUG-002: 招聘季下拉框为空（P2）

- **位置:** `frontend/src/App.vue:349` + `frontend/src/App.vue:1030-1035`
- **症状:** 导入界面招聘季下拉框无预设选项，只有"自定义..."
- **根因:** App.vue 未从 `/api/profile/public` 加载 `available_seasons`，也未传递给 StagingPanel
- **影响:** 用户需手动输入招聘季，体验差
- **严重程度:** P2

---

## BUG-003: JD 表缺少 job_position 字段（P1）

- **位置:** `backend/app/db/operations.py:30-42` + 数据库 schema
- **症状:** 切换目标岗位后，JD 数据不变，所有岗位共享同一份 JD
- **根因:** jd 表 schema 无 `job_position` 列，`_insert_jd()` 不写入岗位
- **影响:** JD 数据不按岗位隔离，多岗位场景下数据混乱
- **严重程度:** P1

---

## BUG-004: 历史面经数据 job_position 为空（P2）

- **位置:** 数据库 interview 表
- **症状:** 所有 30 条面经记录的 `job_position` 为空字符串
- **根因:** 可能在 job_position 功能上线前导入的数据，或导入时未正确传递岗位
- **影响:** 切换岗位后面经数据不变化
- **严重程度:** P2

---

## BUG-005: target 字段未发送（P2）

- **位置:** `frontend/src/components/StagingPanel.vue:222-238`
- **症状:** 所有导入数据默认进入个人题库
- **根因:** `submitAll()` 中无 `formData.append('target', ...)` 调用
- **影响:** 管理员无法通过导入界面提交到公共题库
- **严重程度:** P2

## 复现步骤

### BUG-001
1. 导入界面选择"JD (职位描述)"
2. 粘贴一段 JD 文本，提交
3. **预期:** 使用 JD_PROMPT 解析
4. **实际:** 使用 SYSTEM_PROMPT（LLM 自动判断），可能误判为面经

### BUG-003
1. 当前岗位为"agent开发"，导入一份 JD
2. 切换岗位为"后端开发"
3. 查看 JD 列表
4. **预期:** "后端开发"岗位看不到 agent 开发的 JD
5. **实际:** 所有 JD 在所有岗位下都可见
