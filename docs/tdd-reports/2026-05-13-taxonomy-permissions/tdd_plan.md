# TDD 开发计划

**功能名称:** 分类体系权限管理
**日期:** 2026-05-13
**TDD 状态:** 🔴 红灯阶段准备

## 需求描述

实现分类体系的权限管理功能：
1. 系统默认分类：所有人可见，只有管理员可编辑
2. 用户个人分类：用户自己创建和管理
3. 分享机制：用户可以分享自己的分类给他人使用

## 验收标准

- [ ] 系统分类只有管理员可编辑
- [ ] 普通用户可以创建个人分类
- [ ] 普通用户可以编辑自己的分类
- [ ] 普通用户不能编辑他人的分类
- [ ] 用户可以分享自己的分类
- [ ] 用户可以使用他人分享的分类
- [ ] 分类来源正确标识（system/user/shared）

## 数据库设计

### taxonomy 表增加字段
```sql
ALTER TABLE taxonomy ADD COLUMN source TEXT DEFAULT 'system';  -- system/user/shared
ALTER TABLE taxonomy ADD COLUMN owner_id INTEGER DEFAULT NULL;  -- 用户ID
ALTER TABLE taxonomy ADD COLUMN is_public INTEGER DEFAULT 0;    -- 是否公开分享
```

## 测试清单（按优先级排序）

| ID | 测试场景 | 输入 | 预期输出 | 状态 |
|----|---------|------|----------|------|
| T-001 | 管理员编辑系统分类 | 管理员token + 系统分类 | 成功更新 | ⏳ 待写 |
| T-002 | 普通用户编辑系统分类 | 普通用户token + 系统分类 | 返回403错误 | ⏳ 待写 |
| T-003 | 普通用户创建个人分类 | 普通用户token + 新分类 | 成功创建 | ⏳ 待写 |
| T-004 | 普通用户编辑自己的分类 | 普通用户token + 自己的分类 | 成功更新 | ⏳ 待写 |
| T-005 | 普通用户编辑他人的分类 | 普通用户token + 他人分类 | 返回403错误 | ⏳ 待写 |
| T-006 | 用户分享分类 | 用户token + 分类ID | 成功分享 | ⏳ 待写 |
| T-007 | 获取公开分享的分类 | 用户token | 返回公开分类列表 | ⏳ 待写 |

## 红-绿-重构循环计划

- [ ] 循环 1: T-001 — 实现管理员编辑系统分类
- [ ] 循环 2: T-002 — 实现普通用户编辑系统分类的权限检查
- [ ] 循环 3: T-003 — 实现普通用户创建个人分类
- [ ] 循环 4: T-004 — 实现普通用户编辑自己的分类
- [ ] 循环 5: T-005 — 实现普通用户编辑他人的分类的权限检查
- [ ] 循环 6: T-006 — 实现分享分类功能
- [ ] 循环 7: T-007 — 实现获取公开分享的分类

## 文件变更计划

### 修改文件
- `backend/app/db/connection.py` — 数据库迁移
- `backend/app/db/operations.py` — 分类CRUD操作
- `backend/app/routers/profile.py` — API端点权限检查
- `frontend/src/components/SettingsPanel.vue` — 前端权限控制
