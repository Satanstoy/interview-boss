# Bug 详细分析报告

**Bug ID:** BUG-001, BUG-002, BUG-003, BUG-004
**发现日期:** 2026-05-13
**状态:** 已确认

## 问题概述
用户采纳AI生成的分类后，切换岗位再返回或点击"保存全局配置"，采纳的分类丢失。

## 根本原因分析

### BUG-001: get_taxonomy_for_position 查询不精确
- **位置:** `backend/app/db/connection.py:1007-1045`
- **症状:** 同一岗位有多个分类记录时，返回结果不确定
- **根因:** SQL 查询只按 `position_name` 过滤，不区分 `source` 和 `owner_id`
- **影响:** 可能返回系统默认分类而非用户个人分类
- **严重程度:** P1 (High)

### BUG-002: confirm_taxonomy 保存到系统分类
- **位置:** `backend/app/routers/profile.py:414-429`
- **症状:** AI采纳的分类保存到系统分类而非用户个人分类
- **根因:** 调用 `save_taxonomy_suggestion` 时使用默认参数 `source='system'` 和 `owner_id=None`
- **影响:** 用户采纳的分类可能被系统分类覆盖
- **严重程度:** P1 (High)

### BUG-003: 保存全局配置导致分类丢失
- **位置:** `backend/app/routers/profile.py:336`
- **症状:** 用户采纳AI分类后点击"保存全局配置"，分类丢失
- **根因:** `update_profile` 端点调用 `save_taxonomy_for_position(position, tc["categories"])` 时未传递 `source` 和 `owner_id` 参数
- **影响:** 用户的个人分类配置被覆盖为系统分类
- **严重程度:** P1 (High)

### BUG-004: get_profile 未传递 user_id 导致无法加载用户个人分类
- **位置:** `backend/app/routers/profile.py:298`
- **症状:** 管理员打开设置面板时，总是显示系统分类而非用户个人分类
- **根因:** `get_profile` 端点调用 `get_taxonomy_for_position(current_pos)` 时未传递 `user_id` 参数
- **影响:** 用户个人分类无法被加载显示
- **严重程度:** P0 (Critical)

### 附带问题: save_taxonomy_for_position NULL owner_id UPSERT 失败
- **位置:** `backend/app/db/connection.py:1049-1068`
- **症状:** 系统分类（owner_id=NULL）每次保存都创建新行
- **根因:** SQLite 的 `ON CONFLICT` 在 owner_id 为 NULL 时无法匹配（NULL != NULL）
- **影响:** 数据库中积累大量重复的系统分类行
- **严重程度:** P2 (Medium)

## 复现步骤

### BUG-003 & BUG-004
1. 登录系统（管理员账号）
2. 打开系统配置
3. 选择岗位
4. 点击"AI 智能生成分类"
5. 等待生成完成，点击"采纳此分类"
6. 点击"保存全局配置"
7. 预期：分类保持为AI采纳的分类
8. 实际：分类恢复为之前的分类

## 修复建议

### BUG-001
修改 `get_taxonomy_for_position` 函数，优先返回用户个人分类（`source='user'`），如果没有则返回系统默认分类（`source='system'`）。

### BUG-002
修改 `confirm_taxonomy` 端点，将分类保存为用户个人分类（`source='user'`，`owner_id=user['id']`）。

### BUG-003
修改 `update_profile` 端点，调用 `save_taxonomy_for_position` 时传递 `source='user'` 和 `owner_id=admin['id']` 参数。

### BUG-004
修改 `get_profile` 端点，调用 `get_taxonomy_for_position` 时传递 `user_id=admin['id']` 参数。

### 附带修复
修改 `save_taxonomy_for_position` 函数，当 `owner_id` 为 NULL 时使用先 UPDATE 再 INSERT 的策略。
