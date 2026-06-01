# TDD 开发计划

**功能名称:** 邮箱验证码登录系统
**日期:** 2026-05-13
**TDD 状态:** 🔴 红灯阶段准备

## 需求描述

为面试备战平台添加邮箱验证码登录功能，包括：邮箱验证码注册、邮箱验证码登录、用户设置中绑定/更换邮箱。

## 验收标准

- [ ] 用户可以通过邮箱验证码注册账号（需邮箱+验证码+密码）
- [ ] 用户可以通过邮箱验证码登录（无需密码）
- [ ] 已登录用户可以在设置中绑定/更换邮箱
- [ ] 验证码5分钟过期，一次性使用
- [ ] 同一邮箱60秒内只能发送一次验证码
- [ ] SMTP配置通过环境变量管理
- [ ] 未配置SMTP时，邮箱相关功能优雅降级（返回提示）

## 架构设计

### 数据库变更

```sql
-- users 表新增字段
ALTER TABLE users ADD COLUMN email TEXT UNIQUE;

-- 新增验证码表
CREATE TABLE IF NOT EXISTS email_verification_codes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL,
    code TEXT NOT NULL,
    purpose TEXT NOT NULL,  -- 'register' | 'login' | 'bind'
    user_id INTEGER,        -- bind 时关联用户
    expires_at TIMESTAMP NOT NULL,
    used INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_email_codes_email ON email_verification_codes(email, purpose, used);
```

### 后端新增文件

| 文件 | 职责 |
|------|------|
| `backend/app/services/email_service.py` | SMTP发送、验证码生成/验证 |
| `backend/app/routers/email_auth.py` | 邮箱认证相关API端点 |

### 后端修改文件

| 文件 | 变更 |
|------|------|
| `backend/app/db/connection.py` | 新增 email 列 + 验证码表 |
| `backend/app/routers/auth.py` | 注册流程增加邮箱验证 |
| `backend/app/routers/profile.py` | 邮箱绑定端点 |
| `backend/app/core/config.py` | SMTP配置项 |
| `backend/.env` | SMTP环境变量 |

### 前端变更

| 文件 | 变更 |
|------|------|
| `frontend/src/components/LoginModal.vue` | 增加邮箱验证码登录/注册模式 |
| `frontend/src/components/SettingsPanel.vue` | 增加邮箱绑定区域 |
| `frontend/src/api/index.js` | 新增API函数 |

### API 设计

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/auth/send-code` | POST | 发送验证码（rate limit: 1/min） |
| `/api/auth/register-with-email` | POST | 邮箱注册（email+code+username+password） |
| `/api/auth/login-with-email` | POST | 邮箱验证码登录（email+code） |
| `/api/profile/bind-email` | POST | 绑定邮箱（email+code） |
| `/api/profile/email` | GET | 获取当前绑定的邮箱 |

## 测试清单（按优先级排序）

| ID | 测试场景 | 输入 | 预期输出 | 状态 |
|----|---------|------|----------|------|
| T-001 | 验证码生成 | - | 6位数字，5分钟有效 | ⏳ 待写 |
| T-002 | 发送验证码-正常 | 有效邮箱 | 成功发送，返回success | ⏳ 待写 |
| T-003 | 发送验证码-频率限制 | 60秒内重复发送 | 返回429 | ⏳ 待写 |
| T-004 | 验证码校验-正确 | 正确code | 返回valid | ⏳ 待写 |
| T-005 | 验证码校验-过期 | 过期code | 返回invalid | ⏳ 待写 |
| T-006 | 验证码校验-已使用 | 已用code | 返回invalid | ⏳ 待写 |
| T-007 | 邮箱注册-正常 | 有效邮箱+验证码+用户名+密码 | 注册成功，返回token | ⏳ 待写 |
| T-008 | 邮箱注册-邮箱已存在 | 已注册邮箱 | 返回409 | ⏳ 待写 |
| T-009 | 邮箱注册-验证码错误 | 错误验证码 | 返回400 | ⏳ 待写 |
| T-010 | 邮箱登录-正常 | 有效邮箱+验证码 | 返回token | ⏳ 待写 |
| T-011 | 邮箱登录-邮箱未注册 | 未注册邮箱 | 返回404 | ⏳ 待写 |
| T-012 | 绑定邮箱-正常 | 有效邮箱+验证码 | 绑定成功 | ⏳ 待写 |
| T-013 | 绑定邮箱-已被其他用户绑定 | 已绑定邮箱 | 返回409 | ⏳ 待写 |
| T-014 | SMTP未配置时发送验证码 | - | 返回503提示 | ⏳ 待写 |

## 红-绿-重构循环计划

- [ ] 循环 1: T-001 验证码生成逻辑
- [ ] 循环 2: T-002~T-006 发送与校验验证码
- [ ] 循环 3: T-007~T-009 邮箱注册
- [ ] 循环 4: T-010~T-011 邮箱登录
- [ ] 循环 5: T-012~T-013 绑定邮箱
- [ ] 循环 6: T-014 优雅降级
- [ ] 循环 7: 前端集成
