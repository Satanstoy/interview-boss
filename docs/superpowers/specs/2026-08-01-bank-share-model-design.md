# 设计规格：题库共享模型重构（废除 bank_mode 三态开关）

> 日期：2026-08-01
> 状态：已实施完成（5 批次全部落地，2026-08-01）
> 关联：`docs/tdd-reports/2026-07-31-embedding-dual-backend.md`（聚类隔离基础设施，本设计保留其语义）

## 1. 背景与问题

「个人题库 vs 公共题库」是早期拍脑袋引入的产品概念，最终长成了一个**全局用户级三态开关**（`users.bank_mode` = public/personal/mixed），并渗透进几乎所有链路：

- 列表/搜索/JD/面经/抽题/练习/分析/答案/chat/MCP 全部要读 `bank_mode` 并三分支
- 4 套 WHERE 构造已漂移（analytics 缺 `duplicate_of IS NULL`、FTS 无 personal 分支）
- `duplicate_of` 镜像机制：个人题命中公共题时写镜像副本到个人库，导致同题双份、mixed 还要排除镜像
- 用户心智断点：普通用户导入面经被强制 `target=personal`，但默认 `bank_mode=public` 时列表里看不到自己导入的题（"我的数据消失了"）
- 权限判断（公共仅 admin / 个人仅本人）重复 6+ 处；services 反向 import routers 的 `_build_bank_where_clause`

## 2. 产品决策（与用户逐项确认）

1. **共享意愿是用户属性**：设置页全局默认（分享 / 仅自己可见）+ 每次导入可覆盖
2. **共享状态单向上升**：私有题可"分享到公共题库"（进审核队列）；公共题不可转私有
3. **视图形态**：单一列表 + 过滤 tabs（全部 / 公共 / 我的），去掉全局开关
4. **分享入口**：题目卡片按钮 + 列表批量操作；分享后进公共 pending 审核队列
5. 注册默认"仅自己可见"（安全优先，防止误分享）

## 3. 目标数据模型

### 3.1 题目两类，不做第三态

| 概念 | 物理表达 | 可见性 |
|------|---------|--------|
| 公共题 | `owner_id IS NULL` + `status='approved'` | 所有人 |
| 待审核公共题 | `owner_id IS NULL` + `status='pending'` + `submitted_by=用户id` | 仅 admin + 贡献者本人（"待审核"徽标） |
| 我的私有题 | `owner_id = 我的id` + `status='approved'` | 仅我 |

### 3.2 废除项

- `users.bank_mode`：废弃不读，前端不再传；注册/登录响应不再返回
- `duplicate_of` 镜像机制：私有题命中公共题时合并删副本，不再写镜像；历史镜像题迁移清理
- `target=personal/public` 导入参数：改为"分享意愿"（`share` / `private`）
- `scan_personal_duplicates`（公共题批准后反扫个人题标镜像）：删除

### 3.3 新增/保留项

- `users.share_default`（migration 051）：`TEXT DEFAULT 'private'`，设置页"分享默认值"
- 导入表单：跟随全局默认 + 可单次覆盖（分享 / 仅自己可见），对所有用户可见（不再仅 admin）
- `question_bank.submitted_by`（已有列）：记录公共 pending 题贡献者
- `question_bank.owner_id`、`analysis_queue.owner_id`、FAISSIndexManager 双层 key：语义不变（聚类隔离继续用）

### 3.4 分享流程（单向上升）

```
私有题 --分享--> 确定性查重（归一化文本精确匹配 + embedding 相似度）
  ├─ 命中已有公共题 → 合并（frequency++）→ 删私有副本 → 完成
  └─ 未命中 → 创建公共 pending（submitted_by=我）→ 私有副本保留（标记"已分享待审核"）
       ├─ admin 批准 → approved → 删私有副本
       └─ admin 驳回 → pending 删除 → 私有副本恢复可再分享
```

## 4. 后端设计

### 4.1 列表/搜索统一过滤参数

`_build_bank_where_clause` 从 `routers/questions.py` 下沉到 `db/queries.py`（消除 services 反向 import routers 的架构倒挂），参数化 `filter`：

```
GET /api/master-bank?filter=all|public|mine
  all    → (owner_id IS NULL AND status='approved') OR (owner_id = 我)
  public → owner_id IS NULL AND status='approved'
  mine   → owner_id = 我  OR (owner_id IS NULL AND status='pending' AND submitted_by = 我)
```

- 现有调用方（抽题、练习、答案、chat、MCP）改为内部固定口径：默认 `all`（公共 + 自己的私有题），不再读 `user.bank_mode`
- 同步修正 analytics 的 mixed 漂移（统一走同一函数后自动消失）
- 频率统计 `get_dynamic_frequency_sql`：公共题只数公共面经、私有题数自己的面经——语义不变，实现收敛进 `queries.py`

### 4.2 分享端点

```
POST /api/master-bank/{id}/share        # 私有题 → 公共 pending（内部先查重：命中则合并删副本）
GET  /api/master-bank/pending/mine      # 我的待审核贡献（"我的"tab 展示）
```

分享去重：**确定性查重**（归一化文本精确匹配 + embedding 相似度），不调 LLM；审核时 LLM 匹配兜底。

### 4.3 审核流程（复用 admin_review 微调）

- 待审核列表/批准逻辑不变（`owner_id IS NULL AND status='pending'`）
- 批准时新增：若该 pending 题的 `submitted_by` 用户仍有同名私有题（分享时保留的副本）→ 删除私有副本
- 驳回时：pending 标记 rejected 或删除，私有副本不动

### 4.4 权限矩阵（抽成单一 helper）

| 操作 | 公共题 | 我的私有题 | 他人私有题 |
|------|--------|-----------|-----------|
| 查看/练习 | 所有用户 | 仅我 | 禁止 |
| 编辑/删除 | 仅 admin | 仅我 | 禁止 |
| 分享 | 不可（已公共） | 仅我 | 禁止 |

### 4.5 响应字段

- `is_personal` 保留（前端徽标用）
- 新增 `share_status`（`private` / `shared_pending` / `public`）供前端展示"已分享待审核"状态

## 5. 前端设计

1. **题库列表页（MasterBankView）**：顶部过滤 tabs「全部 / 公共 / 我的」，各 tab 调 `?filter=...`；徽标：私有「私有」、待审核「待审核」、公共无徽标
2. **QuestionCard**：我的私有题加「分享」按钮（点击确认调 share 端点）；`canDelete/canEdit` 逻辑不变（owner 比对），去掉 bankMode prop 依赖
3. **设置页（SettingsProfile.vue）**：「题库模式」三选卡片 → 「分享默认值」开关（分享 / 仅自己可见）；保存调 `PUT /api/auth/share-default`（新端点，替代 bank-mode 端点）
4. **导入表单（StagingPanel.vue）**：删除「提交到」下拉的 admin 限制 → 「分享设置」（跟随默认 + 可覆盖），所有用户可见；导入完成提示区分"已提交审核/已入库" vs "已存入我的题库"
5. **清理 bank_mode 痕迹**：`useAuth.js` 的 `handleBankModeChanged`、`authUpdateBankMode`、`AuthenticatedLayout.vue` preview 假用户 `bank_mode: 'mixed'`、`AppSidebar.vue` 死监听 `@bank-mode-changed`
6. **透传 bankMode prop 的页面**（`PracticeMode.vue` 等）：全部移除，后端默认 `all` 口径后前端无需传参
7. **路由**：保持单一路由 `/master-bank`

## 6. 数据迁移

1. **历史 `duplicate_of` 镜像题清理**：`owner_id=user_id AND duplicate_of IS NOT NULL` 的个人镜像题软删除（新视图 all 已能看到公共题本身，镜像冗余）；迁移脚本 `scripts/fix_duplicate_of_mirrors.py`（dry-run + 执行）
2. **`users.bank_mode`**：保留列不读，不迁移数据；后端 `get_current_user` 不再返回；auth 端点删除 bank-mode 读写
3. **`users.share_default`**（migration 051）：加列 `TEXT DEFAULT 'private'`；注册写入默认 `'private'`
4. **聚类/队列不受影响**：`analysis_queue.owner_id` 分桶、FAISSIndexManager 双层 key、`cluster_batch` 隔离逻辑全部保留

## 7. 测试策略（TDD）

| 层 | 覆盖 |
|----|------|
| 后端单元 | WHERE 三口径（all/public/mine）+ pending 贡献者可见性；share 端点（命中合并/未命中建 pending/权限）；share_default 读写；权限矩阵 helper |
| 后端集成 | 分享→审核→批准删副本全链路；驳回保留私有副本；频率统计口径回归；聚类隔离不回归 |
| 数据迁移 | 脚本 dry-run/执行 + duplicate_of 清理正确性 |
| 前端 | Playwright：tabs 过滤、分享按钮流程、设置页开关、导入分享选项、徽标展示（mock API） |
| 回归 | 现有 pipeline/services/chat/security 全部通过 |

## 8. 实施拆解

| 批次 | 内容 | 关键文件 |
|------|------|---------|
| ① 后端数据层 | migration 051（share_default）+ WHERE 收敛到 queries.py + 权限 helper + 删 bank_mode 读取 | `db/queries.py`、`routers/questions.py`、`auth.py`、`question_draw_service.py`、`analytics.py`、`data.py`、`mcp_server/`、chat 相关 |
| ② 后端分享链路 | share 端点 + pending/mine + 审核批准删副本 + 删 scan_personal_duplicates + 删 duplicate_of 写入 | `routers/questions_pkg/mutations.py`、`admin_review.py`、`bank_build.py` |
| ③ 数据迁移脚本 | duplicate_of 镜像清理脚本（dry-run + 执行） | `scripts/fix_duplicate_of_mirrors.py` |
| ④ 前端重构 | tabs + 分享按钮 + 设置页开关 + 导入分享选项 + 清 bank_mode 痕迹 | `MasterBankView`、`QuestionCard`、`SettingsProfile`、`StagingPanel`、`useAuth`、`authApi` |
| ⑤ 收尾 | Playwright E2E + 全量回归 + 文档更新（CLAUDE.md/README） | 前端测试 + docs |

## 9. 风险与回滚

- 最大风险：视图口径从"全局模式"切到"filter 参数"，存量接口调用方要逐一核对（抽题/练习/chat/MCP 已排查）
- 回滚：migration 051 可逆；前端 dist 回滚用 `./deploy/docker-deploy.sh frontend`

## 10. 实施完成记录（2026-08-01）

- 批次① 后端数据层：migration 051（users.share_default 默认 private）、build_bank_where_clause 下沉 db/queries.py（all/public/mine）、can_edit_question 权限矩阵、auth 端点 bank-mode→share-default、全链路 bank_mode 读取清理（questions/analytics/data/draw/chat/mcp）、get_current_user token type 防御加固
- 批次② 分享链路：questions_pkg/share.py（查重/合并/建 pending/pending-mine）、审核批准删副本、删除 scan_personal_duplicates 与 duplicate_of 写入路径
- 批次③ 迁移脚本：scripts/fix_duplicate_of_mirrors.py（dry-run 已对生产库验证，1 条镜像待清理）
- 批次④ 前端：MasterBankView filter tabs（全部/公共/我的）、QuestionCard 分享按钮+私有徽标、SettingsProfile 分享默认值开关、StagingPanel 分享选项（所有用户可见）、bank_mode 痕迹清理
- 批次⑤ 收尾：全量回归 958 passed / 5 known failed / 0 新回归；前端 build 通过
- E2E 补充（Playwright，mock API）：`tests/e2e/bank-share-model.spec.js` 4 个用例全过（tabs 过滤 / 分享按钮+私有徽标 / 设置页分享默认值 / 导入页分享选项）；期间修复 3 个前端 bug：AuthenticatedLayout 未透传 bankFilter、authApi 导出名残留、AccordionTrigger 内嵌套 button 非法 HTML（徽标/分享按钮移至 QuestionCard 答案区，contentOnly 也渲染）

## 11. 待实现时细化的遗留项（已落地部分标注）

- ~~分享去重的确定性查重实现细节~~ → 已实现：归一化文本精确匹配（find_matching_public_question）
- ~~pending 题在"我的"tab 的展示形态~~ → 已实现：mine 口径含 submitted_by=me 的 pending 贡献
- ~~审核驳回的 rejected 状态是否保留记录~~ → 保留 rejected 状态（沿用现有 reject 端点）

## 12. 已知待办（部署时）

- 生产库执行 `python backend/scripts/fix_duplicate_of_mirrors.py` 清理镜像题（部署后）
- 前端 smoke/E2E 测试需在安装 Chromium 的环境跑（本地缺 chrome）

- 分享去重的确定性查重实现细节（归一化文本精确匹配 + embedding 相似度阈值）
- pending 题在"我的"tab 的展示形态（是否区分"已分享待审核"徽标位置）
- 审核驳回的 rejected 状态是否保留记录（merge_history / 单独状态）
