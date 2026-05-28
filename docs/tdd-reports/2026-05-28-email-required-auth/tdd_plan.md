# TDD 开发计划

**功能名称:** 注册强制绑定邮箱 + 登录检测邮箱绑定
**日期:** 2026-05-28
**TDD 状态:** 🔴 红灯阶段准备

## 需求描述

用户注册必须提供邮箱，已有用户登录时若未绑定邮箱则提示绑定，绑定完成后才能正常使用系统。

## 验收标准

- [ ] 注册时没有邮箱返回 400
- [ ] 注册时邮箱格式错误返回 400
- [ ] 注册时邮箱已被占用返回 409
- [ ] 注册时提供合法邮箱成功创建用户
- [ ] 登录用户有邮箱 → 正常返回 token
- [ ] 登录用户无邮箱 → 返回 `need_email_bind` + 临时 token
- [ ] 临时 token 只能用于绑定邮箱（type=email_bind, 30min 有效期）
- [ ] 用临时 token + 验证码绑定邮箱成功
- [ ] 绑定邮箱后可以正常登录
- [ ] 临时 token 过期返回 401
- [ ] 前端注册表单显示邮箱输入框
- [ ] 前端登录收到 `need_email_bind` 时显示邮箱绑定界面

## 测试清单（按优先级排序）

### 后端测试

| ID | 测试场景 | 输入 | 预期输出 | 状态 |
|----|---------|------|----------|------|
| T-001 | 注册无邮箱被拒绝 | `{username, password}` | 400 | ⏳ |
| T-002 | 注册邮箱格式错误 | `{username, password, email:"bad"}` | 400 | ⏳ |
| T-003 | 注册邮箱已被占用 | `{username, password, email}` (email 已存在) | 409 | ⏳ |
| T-004 | 注册有邮箱成功 | `{username, password, email:"ok@test.com"}` | 200 + token | ⏳ |
| T-005 | 登录用户有邮箱 | 用户 email != NULL | 200 + token | ⏳ |
| T-006 | 登录用户无邮箱 | 用户 email IS NULL | 200 + need_email_bind + temp_token | ⏳ |
| T-007 | 临时 token 绑定邮箱成功 | temp_token + valid code | 200 + 正式 token | ⏳ |
| T-008 | 临时 token 绑定邮箱-验证码错误 | temp_token + wrong code | 400 | ⏳ |
| T-009 | 临时 token 过期 | 过期的 temp_token | 401 | ⏳ |
| T-010 | 临时 token 不能访问其他 API | temp_token 调用 /api/data | 401/403 | ⏳ |

### 前端测试

| ID | 测试场景 | 状态 |
|----|---------|------|
| T-011 | 注册表单有邮箱输入框 | ⏳ |
| T-012 | 登录收到 need_email_bind 显示绑定界面 | ⏳ |
| T-013 | 绑定邮箱后正常登录 | ⏳ |

## 实现策略

### 后端改动

1. **RegisterRequest** — 新增 `email` 字段（必填，5-120 字符）
2. **POST /api/auth/register** — 验证邮箱格式、检查唯一性、写入 email 列
3. **POST /api/auth/login** — 密码验证通过后检查 `user.email`，无邮箱返回 `need_email_bind` + 临时 token
4. **create_email_bind_token** — 新函数，签发 `type="email_bind"` JWT（30min 有效）
5. **POST /api/auth/bind-email-with-token** — 新端点，接受临时 token + 验证码，绑定邮箱并返回正式 token
6. **get_current_user** — 临时 token 的 `type` 不是 "access"，拒绝访问

### 前端改动

1. **LoginModal.vue** — 注册模式增加邮箱输入框；处理 `need_email_bind` 响应
2. **authApi.js** — register 传 email；新增 bindEmailWithToken API
