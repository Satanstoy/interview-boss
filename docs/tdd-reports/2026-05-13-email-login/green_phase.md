# 绿灯阶段报告

**测试编号:** T-001 ~ T-017
**实现时间:** 2026-05-13

## 实现内容

### 1. `backend/app/services/email_service.py` — 验证码服务
- `generate_verification_code()`: 6位数字验证码
- `send_verification_code(email, purpose)`: 发送验证码（含频率限制、SMTP检查）
- `verify_code(email, code, purpose)`: 校验验证码（过期、已使用检查）
- `_smtp_send(to_addr, subject, body)`: SMTP邮件发送
- `_get_smtp_config()`: 从环境变量读取SMTP配置

### 2. `backend/app/routers/auth.py` — 邮箱认证端点
- `POST /api/auth/send-code`: 发送验证码（3/min限流）
- `POST /api/auth/register-with-email`: 邮箱注册
- `POST /api/auth/login-with-email`: 邮箱验证码登录

### 3. `backend/app/routers/profile.py` — 邮箱绑定端点
- `POST /api/profile/bind-email`: 绑定/更换邮箱
- `GET /api/profile/email`: 获取当前绑定邮箱
- `POST /api/profile/send-bind-code`: 发送绑定验证码

### 4. `backend/app/db/connection.py` — 数据库迁移
- `users` 表新增 `email TEXT` 列
- 新增 `email_verification_codes` 表

## 测试运行结果

```
17 passed in 2.46s
```

## 阶段状态

- [x] 最小实现已编写
- [x] 测试通过（绿色）
- [ ] 进入重构阶段
