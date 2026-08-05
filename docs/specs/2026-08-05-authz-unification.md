# Spec: 鉴权体系收敛 — 统一 RBAC+ABAC 授权决策点

> 位置: 后端 `auth.py` / `questions.py` / `practice.py` / `answers.py` / `bank_build.py` / `practice_deck_service.py` / `bulk.py` + 前端 `AuthenticatedLayout.vue` / `PracticeDeckManager.vue`
> 类型: 安全审计修复 spec
> 日期: 2026-08-05
> 状态: 待实施
> 触发背景: 对「公共题库/个人题库」与「普通用户/管理员」两组关系的全面鉴权审计，发现 1 高危 + 4 中危 + 5 低危权限问题。根因是权限决策逻辑散落多层的内联 if（RBAC+ABAC 设计意图正确，工程实现未收敛）。

## 结论

系统设计意图是 **RBAC（`is_admin` 粗粒度角色）+ ABAC（资源属性：owner_id/status/submitted_by 细粒度判断）**。本次改造把它收敛为**单一授权决策点（PDP）**：

1. 所有按 ID 访问的端点必须经过统一可见性断言（一切资源查询都带 scope）
2. 编辑权限收敛到唯一 `can_edit_question`（个人题仅本人，admin 也不能改他人个人题）
3. 自定义题单私有化（owner-only，不可被他人看到或管理）
4. 堵住 build-personal 绕过审核写公共数据的旁路
5. 补「跨归属访问必须失败」回归测试契约

## 决策记录（2026-08-05 用户拍板）

| # | 决策 | 选择 |
|---|------|------|
| D1 | M3 权限矩阵统一语义 | **admin 也不能改个人题**（强所有权边界） |
| D2 | M1 合并流程 | **非 admin 合并只落个人题**，绝不写公共表 |
| D3 | M2 存量 public 题单 | **不迁移**，API 强制 owner-only 后存量自动对他人不可见 |
| D4 | L2 预览模式 | **预览按普通用户渲染**（previewUser 去 is_admin） |
| D5 | L4 回收站口径 | **admin 仅看公共题回收站**，个人题仅本人 |
| D6 | use-reference-answer | **彻底删除**端点 |

## 现状问题清单

| 级别 | 问题 | 位置 |
|------|------|------|
| 🔴 H1 | `GET /api/master-bank/{id}/detail` 无可见性过滤（IDOR），按 ID 枚举可读他人私有题/待审题/回收站题的 ai_answer 与来源 | `questions.py:218-255` |
| 🟠 M1 | `build-personal` 非 admin 合并时直接 UPDATE/DELETE 公共题（绕过 share→pending→approve 审核），污染公共来源/频率 | `bank_build.py:442-459` |
| 🟠 M2 | 公开自定义题单（visibility='public'）无 owner 校验，任何登录用户可增删题目 | `practice_deck_service.py:84-89,326,354` |
| 🟠 M3 | 编辑权限三入口三种规则：router 放行 admin 改他人个人题（`questions.py:313-321`）、`can_edit_question` 禁止（`queries.py:190-198`）、`data.py:772-786` 一律 403 | 见左 |
| 🟠 M4 | `use-reference-answer` 无可见性校验（决策：删除端点） | `answers.py:18-53` |
| 🟡 L1 | `save-user-answer` 只查题目存在，不校验可见性 | `answers.py:56-83` |
| 🟡 L2 | 预览模式 `previewUser` 伪造 `is_admin: true` | `AuthenticatedLayout.vue:279-285` |
| 🟡 L3 | `get_current_user` 不 SELECT `bank_mode` → `_build_bank_where_clause(user)` 恒 "public" → 个人题无法收藏/复习/背诵（404），与 deck 服务行为不一致 | `auth.py:202` |
| 🟡 L4 | `GET /api/master-bank/trash` admin 分支暴露所有用户个人题回收站（含 owner_id） | `bulk.py:219-238` |
| 🟡 L5 | `JWT_SECRET` 长度仅警告不拒绝 | `auth.py:17-18` |

## 详细设计

### 1. 统一授权决策点（PDP 收敛）

**L3 修复（根因一行）**：`auth.py` `get_current_user` 的 SELECT 增加 `bank_mode` 字段：
```sql
SELECT id, username, is_admin, share_default, current_position_id, bank_mode FROM users WHERE id = ?
```
`questions.py:29` 的 deprecated wrapper 委托 queries 版 `build_bank_where_clause` 逻辑正确，恢复 bank_mode 后全链路自动回到正确口径。**不做结构性重构**（不引入新模块），复用现有 `db/queries.build_bank_where_clause` + `db/queries.can_edit_question` 作为唯一决策函数。

### 2. H1 + L1：按 ID 访问端点补可见性断言

- **detail**（`questions.py:218`）：查询 SQL 改为 `SELECT ... {_build_bank_where_clause(user)} AND qb.id = ?`（`filter_mode=all` 口径：公共 approved OR 自己的），无结果 404。
- **save-user-answer**（`answers.py:56`）：调用前复用 `_assert_question_visible` 模式做可见性断言（个人题也允许——用户为自己的背诵稿保存），不可见 404。

### 3. M3：编辑权限唯一化

- `questions.py:313-321` PUT 编辑校验改为 `can_edit_question(row["owner_id"], user["id"], user.get("is_admin", 0))`，不满足 403。
- `data.py:772-786` 通用更新接口：个人题（owner_id 非空）一律 403 保持现状，公共题字段白名单保持（config.py:60-69）。
- 删除 `db/queries.py` 中与 `can_edit_question` 注释冲突的歧义说明（如有），docstring 明确唯一语义：**公共题仅 admin；个人题仅本人（admin 也不能改）**。

### 4. M4：删除 use-reference-answer

- 删除 `answers.py:18-53` 端点 + 路由注册。
- 清理 `test_per_user_answers.py` 中 T-002/T-003 相关用例。
- 前端 `masterBankApi.js` 的 `useReferenceAnswer` 与 `api/index.js` re-export 一并删除（上一轮已删调用方，现删定义）。

### 5. M2：自定义题单私有化（owner-only）

`practice_deck_service.py`：
- `get_deck_definition`（:84-89）：`WHERE deck_key = ? AND owner_id = ?`（去掉 `OR visibility = 'public'`）。
- `list_decks`（:175-193）：`custom_where` 仅 `owner_id = ?`；`filter_mode=public` 分支不再返回自定义题单（改为 `WHERE 1=0` 或直接不查）；`mine` 分支不变。
- `add_deck_item` / `remove_deck_item`（:326, :354）：`get_deck_definition` 改后自然仅 owner 可达，不满足即 `KeyError`（404），无需额外逻辑。
- `create_deck` / `update_deck` 的 `visibility` 参数：**保留字段与 API 参数**（避免破坏前端与存量数据），但服务端不再有任何返回/读取 public 题单的路径。
- 前端 `PracticeDeckManager.vue`：删除「可见范围」select（:119）与 `Globe2` 图标分支（:160，custom 统一 `LockKeyhole`）；`form.visibility` 恒为 `'private'`（:144,173,178,182 保留赋值）。

### 6. M1：build-personal 合并只落个人题

`bank_build.py` `_merge`（:330-470）：
- 非 admin 用户匹配到公共题时：**不执行公共题的 UPDATE/DELETE**；仅把公共题的 `sources/original_questions/original_question_sources` 数据并入**用户个人题记录**（`personal_row` 仍保留为独立个人题，不删除）。
- admin 用户维持现状（可合并进公共题）。
- 若个人题与公共题重复合并是产品预期行为（去重），由管理员后续通过现有 merge 端点处理。

### 7. L4：回收站口径

`bulk.py:219-238` admin 分支查询增加 `AND owner_id IS NULL`（仅公共题），普通用户分支不变。docstring 同步更新。

### 8. L2：预览模式按普通用户渲染

`AuthenticatedLayout.vue:279-285`：`previewUser` 的 `is_admin` 改为 `false`。预览模式下管理员入口（生成答案/审核/批量/合并/聚类）全部不渲染。

### 9. L5：JWT_SECRET 强度

`auth.py:17-18`：`JWT_SECRET` 长度 <32 字节时改为 **RuntimeError 拒绝启动**（生产环境不允许弱密钥），并保留现有自动生成 `.env` 逻辑。

## 接口变更汇总

| 接口 | 变更 |
|------|------|
| `GET /api/master-bank/{id}/detail` | 补可见性过滤（404 不可见） |
| `PUT /api/master-bank/{id}` | 个人题仅本人可编辑（admin 也 403） |
| `POST /api/master-bank/use-reference-answer/{id}` | **删除** |
| `PUT /api/master-bank/save-user-answer/{id}` | 补可见性断言 |
| `POST /api/master-bank/build-personal` | 非 admin 合并只落个人题 |
| `GET /api/practice/decks` | 不再返回他人自定义题单（含 filter=public） |
| `POST/DELETE /api/practice/decks/{k}/items*` | 他人题单 404 |
| `GET /api/master-bank/trash` | admin 仅见公共题 |
| `GET /api/auth/me`（get_current_user 内部） | 返回 bank_mode |

## 测试策略（跨归属访问必须失败契约）

按 WorkOS *cross-tenant access attempts must fail* 原则，为每个资源端点补回归测试（`backend/tests/security/` 或对应领域目录）：

| 用例 | 断言 |
|------|------|
| 他人个人题 detail | 404 |
| 他人个人题 PUT 编辑 | 403（admin 也 403） |
| 他人自定义题单 get_deck_definition / list_decks | 不可见 |
| 他人自定义题单 add/remove item | 404 |
| use-reference-answer 端点 | 路由不存在 404 |
| save-user-answer 对不可见题 | 404 |
| 非 admin build-personal 命中公共题 | 公共题行不被 UPDATE/DELETE（断言 DB 行不变） |
| trash admin 分支 | 不含他人个人题 |
| get_current_user | 返回 bank_mode 字段 |
| 个人题收藏/复习/背诵（L3 回归） | 不 404 |

## 实施顺序

- **Phase A（L3 根因 + H1 + L1 + M4）**：`auth.py` bank_mode → detail/save-user-answer 可见性 → 删除 use-reference-answer。独立可上线，关闭高危 IDOR。
- **Phase B（M3）**：编辑权限收敛到 `can_edit_question`。
- **Phase C（M2 + 前端）**：题单私有化 + PracticeDeckManager UI。
- **Phase D（M1）**：build-personal 非 admin 只落个人题。
- **Phase E（L2/L4/L5）**：预览角色、回收站口径、密钥强度。
- 每阶段跑对应领域测试 + 最终 `check` 门禁。

## 不在范围内

- 不引入外部策略引擎（OPA/Cedar/OpenFGA）——SQLite 单机应用用收敛的 Python 决策函数即可。
- 不做题单分享/协作功能（本轮决策为纯私有，未来如需协作再上 ReBAC）。
- 不迁移存量 `visibility='public'` 数据（D3）。
- 不新增角色体系（维持单一 is_admin）。

## 风险与对策

| 风险 | 对策 |
|------|------|
| build-personal 行为变化影响导入体验（个人题不再并入公共题） | 个人题仍保留全部数据并可见，仅不再写公共表；提示文案可在前端同步调整 |
| L3 修复后个人题出现在收藏/复习队列，测试覆盖不足 | Phase A 补 L3 回归用例 |
| 删除 use-reference-answer 影响旧前端缓存调用 | 前端构建产物一并更新，后端 404 无害 |
| admin 无法再编辑用户个人题（客服场景受限） | 保持强所有权边界（D1），需要时由用户自行操作 |
