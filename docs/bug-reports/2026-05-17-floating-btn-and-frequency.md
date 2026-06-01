# 悬浮按钮位置 + 频率显示修复

**日期：** 2026-05-17
**类型：** Bug 修复
**状态：** 完成

## Bug 1: 回到题库悬浮按钮位置错误

**现象：** 从高频题库点击题目来源跳转到面经模块后，"返回题库"悬浮按钮跟随高亮行定位，位置不固定。

**根因：** `positionFloatingBtn()` 使用 `getBoundingClientRect()` 将按钮定位在高亮行的右侧，随着滚动不断变化位置。

**修复：** 改为固定定位在页面左上角（`top: 12px, left: 12px`），不再跟随行位置。

**文件：** `frontend/src/App.vue` — `positionFloatingBtn()`

## Bug 2: 频率数字与来源数量不对应

**现象：** 题库中显示的"频率 N"与展开后看到的来源数量不一致。

**根因：** `build_api_shapes_batch` 和 `build_api_shapes_batch_filtered` 中 frequency 设为 `len(original_items)`（原始问题文本数），而非 `len(sources)`（来源 URL 数）。一道聚类题可能有 5 条原始问题但只来自 3 个面经 URL。

**修复：** frequency 改为 `len(sources)` — 即该题出现在多少个面经中（与前端"频率"语义一致）。

**文件：** `backend/app/db/question_bank_sources.py` — 两处 `frequency` 字段
