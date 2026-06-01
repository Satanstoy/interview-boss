# Bug 详细分析报告

**Bug ID:** BUG-001
**发现日期:** 2026-05-13
**状态:** 已确认

## 问题概述
用户点击"采纳此分类"按钮后，后端抛出 `sqlite3.OperationalError`，导致 AI 生成的分类无法保存到数据库。

## 根本原因分析

### BUG-001: UPSERT 语句与唯一索引不匹配
- **位置:** `backend/app/db/connection.py:1038-1043`
- **症状:** `sqlite3.OperationalError: ON CONFLICT clause does not match any PRIMARY KEY or UNIQUE constraint`
- **根因:** 在实现分类权限管理功能时，将 taxonomy 表的唯一索引从 `position_name` 改为复合索引 `(position_name, source, owner_id)`，但 `save_taxonomy_for_position()` 函数的 UPSERT 语句仍使用 `ON CONFLICT(position_name)`，与新的复合索引不匹配。
- **影响:** 所有调用 `save_taxonomy_for_position()` 的功能都会失败，包括：
  - AI分类采纳 (`/api/profile/taxonomy/confirm`)
  - 分类保存
- **严重程度:** P0 (Critical)

## 复现步骤
1. 登录系统
2. 打开系统配置
3. 选择目标岗位
4. 点击"AI 智能生成分类"
5. 等待 AI 生成完成
6. 点击"采纳此分类"
7. 预期：分类保存成功
8. 实际：服务器内部错误

## 修复方案
修改 `save_taxonomy_for_position()` 函数，使用正确的 UPSERT 语法匹配复合唯一索引 `(position_name, source, owner_id)`。

对于系统默认分类的保存，应使用 `source='system'` 和 `owner_id=NULL`。
