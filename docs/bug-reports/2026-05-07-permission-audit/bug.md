# Bug 详细分析报告

**日期:** 2026-05-07
**状态:** 已确认

## 问题概述
权限审计发现 1 个后端运行时错误和 7 个前端权限守卫缺失问题。

---

## BUG-001: `build-personal` 路由引用未定义变量 `admin`（P0 — 运行时崩溃）

- **位置:** `backend/app/routers/master_bank.py:420`
- **症状:** 普通用户调用 `POST /api/master-bank/build-personal` 时，后端抛出 `NameError: name 'admin' is not defined`，返回 500 错误
- **根因:** 函数参数名为 `user`（第 358 行 `user: dict = Depends(get_current_user)`），但第 420 行错误引用了 `admin['id']`
- **影响:** 个人题库与公共题库聚类合并功能完全不可用
- **严重程度:** P0

```python
# 第 358 行 — 参数名是 user
async def build_personal_bank(user: dict = Depends(get_current_user)):
    ...
    # 第 420 行 — 错误引用了 admin
    match_result = await match_new_questions(new_rows_for_match, existing_by_cat2, user_id=admin['id'])
```

---

## BUG-002: "重建题库"按钮对普通用户可见（P1）

- **位置:** `frontend/src/App.vue:157-172`
- **症状:** 所有登录用户都能看到"重建题库"按钮，点击后收到 403
- **根因:** 按钮无 `v-if="currentUser?.is_admin"` 守卫
- **影响:** 普通用户应只看到"重建个人题库"按钮（调用 `build-personal`），而非"重建题库"（调用 admin-only 的 `build`）
- **严重程度:** P1

---

## BUG-003: "重新分类"按钮对普通用户可见（P2）

- **位置:** `frontend/src/components/QuestionCard.vue:57-61`
- **症状:** 每张题目卡片上都有"重新分类"按钮，普通用户点击后 403
- **根因:** 按钮无管理员权限守卫
- **影响:** 用户体验混乱
- **严重程度:** P2

---

## BUG-004: "独立"/"合并到"按钮对普通用户可见（P2）

- **位置:** `frontend/src/components/QuestionCard.vue:151-158`
- **症状:** 多来源题目的"独立"和"合并到"按钮对所有用户可见
- **根因:** 按钮无管理员权限守卫
- **影响:** 用户体验混乱
- **严重程度:** P2

---

## BUG-005: JD/面经数据表删除按钮对普通用户可见（P2）

- **位置:** `frontend/src/App.vue:240-243`（JD 删除）、`297-300`（面经删除）
- **症状:** 数据表中每行都有删除按钮，普通用户点击后 403
- **根因:** 按钮无管理员权限守卫
- **严重程度:** P2

---

## BUG-006: 面经"分析"按钮对普通用户可见（P2）

- **位置:** `frontend/src/App.vue:288-292`
- **症状:** 面经表中每行都有"分析"（重新处理）按钮
- **根因:** 按钮无管理员权限守卫
- **严重程度:** P2

---

## BUG-007: 内联编辑字段对普通用户可见（P2）

- **位置:** `frontend/src/App.vue:247-259`（JD 行）、`304-319`（面经行）
- **症状:** 数据表中所有 InlineEdit 字段可被普通用户编辑
- **根因:** InlineEdit 组件无管理员权限守卫
- **严重程度:** P2

---

## BUG-008: 批量操作面板对普通用户可见（P2）

- **位置:** `frontend/src/App.vue:606-665`
- **症状:** JD 和面经的 BatchActionPanel（批量删除、批量重新分析）对普通用户可见
- **根因:** 批量操作定义中无管理员过滤
- **严重程度:** P2

## 复现步骤

### BUG-001 复现
1. 以普通用户登录
2. 上传个人题目到个人题库
3. 调用 `POST /api/master-bank/build-personal`
4. **预期:** 返回合并结果
5. **实际:** 500 错误，日志显示 `NameError: name 'admin' is not defined`

### BUG-002~008 复现
1. 以普通用户登录
2. 浏览高频题库、JD、面经页面
3. **预期:** 管理员专用按钮不可见
4. **实际:** 所有按钮均可见，点击后收到 403 错误

## 修复建议
1. BUG-001: 将 `admin['id']` 改为 `user['id']`
2. BUG-002: 将"重建题库"按钮拆分为管理员版（重建公共题库）和普通用户版（重建个人题库）
3. BUG-003~008: 为所有管理员专用 UI 元素添加 `v-if="currentUser?.is_admin"` 或通过 props 传递 `isAdmin`
