# Bug 详细分析报告

**Bug ID:** BUG-001, BUG-002
**发现日期:** 2026-05-13
**状态:** 已确认

## 问题概述
1. 新增岗位时服务器内部错误
2. 缺少岗位删除功能

## 根本原因分析

### BUG-001: 新增岗位时 UPSERT 语句与唯一索引不匹配
- **位置:** `backend/app/routers/profile.py:536-541`
- **症状:** `sqlite3.OperationalError: ON CONFLICT clause does not match any PRIMARY KEY or UNIQUE constraint`
- **根因:** `switch_position` 端点在创建新岗位时，向 taxonomy 表插入数据使用 `ON CONFLICT(position_name) DO NOTHING`，但数据库唯一索引已变更为复合索引 `(position_name, source, owner_id)`
- **影响:** 新增岗位功能完全不可用
- **严重程度:** P1 (High)

### BUG-002: 缺少岗位删除功能
- **位置:** 前端和后端均未实现
- **症状:** 已有岗位没有删除选项
- **根因:** 功能未实现
- **影响:** 无法管理多余岗位
- **严重程度:** P2 (Medium)

## 复现步骤

### BUG-001
1. 登录系统（管理员账号）
2. 打开系统配置
3. 在"新增岗位"输入框输入新岗位名称
4. 点击"添加"按钮
5. 预期：岗位添加成功
6. 实际：服务器内部错误

### BUG-002
1. 登录系统（管理员账号）
2. 打开系统配置
3. 查看已有岗位列表
4. 预期：有删除按钮
5. 实际：没有删除选项

## 修复建议

### BUG-001
修改 `switch_position` 端点中的 SQL 语句，使用正确的 `ON CONFLICT` 子句匹配复合唯一索引。

### BUG-002
1. 后端：添加 `DELETE /api/profile/position/{id}` 端点（软删除）
2. 前端：为管理员在岗位标签旁添加删除按钮
