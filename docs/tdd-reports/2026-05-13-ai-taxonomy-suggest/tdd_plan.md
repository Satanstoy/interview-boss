# TDD 开发计划

**功能名称:** AI智能生成分类体系
**日期:** 2026-05-13
**TDD 状态:** 🔴 红灯阶段准备

## 需求描述

在系统配置界面（SettingsPanel），目标岗位选择下方提供"AI生成分类"按钮，用户点击后调用LLM根据岗位特征生成推荐的一级大类和二级子类分类体系，预览后由用户决定是否采纳（覆盖当前分类）。

## 架构决策：公共题库分类不匹配问题

### 现状分析
- `taxonomy` 表按岗位存储分类体系结构（JSON）
- `question_bank` 表中每道题的 `cat1`/`cat2` 是硬编码值
- 修改 taxonomy 不会自动更新已有题目的分类值
- 聚类引擎按 `cat2` 分组，改了taxonomy不影响已入库题目

### 解决策略：MVP阶段采用策略A（仅更新taxonomy）
- AI生成新分类 → 用户确认 → 仅更新 `taxonomy` 表
- 已有题目的 `cat1`/`cat2` 保持不变
- 新打标的题目会使用新分类体系
- 旧题目可以通过后续的"批量重打标"功能逐步迁移

### 未来扩展点
- 批量重打标功能（策略B）
- 分类映射迁移功能（策略C）

## 验收标准

- [ ] 点击"AI生成分类"按钮，调用LLM返回推荐分类
- [ ] 返回的分类格式正确（包含cat1和children）
- [ ] 用户确认后，taxonomy表被更新
- [ ] 用户取消后，不做任何修改
- [ ] LLM调用失败时，显示错误提示
- [ ] 生成过程中显示loading状态
- [ ] 空岗位名时，按钮禁用或提示

## 测试清单（按优先级排序）

| ID | 测试场景 | 输入 | 预期输出 | 状态 |
|----|---------|------|----------|------|
| T-001 | 正常生成分类 | 有效岗位名 | 返回包含cat1和children的分类列表 | ⏳ 待写 |
| T-002 | 保存分类到数据库 | 用户确认采纳 | taxonomy表更新为新分类 | ⏳ 待写 |
| T-003 | 取消不保存 | 用户取消 | taxonomy表不变 | ⏳ 待写 |
| T-004 | LLM返回格式异常 | LLM返回非JSON | 抛出/捕获错误 | ⏳ 待写 |
| T-005 | 空岗位名 | 空字符串 | 返回400错误 | ⏳ 待写 |
| T-006 | LLM调用超时 | 网络超时 | 返回超时错误 | ⏳ 待写 |

## 测试用例详细设计

### T-001: 正常生成分类
```python
def test_generate_taxonomy_returns_valid_structure():
    """LLM返回的有效JSON应被正确解析为分类结构"""
    # Mock LLM返回标准格式
    # 验证返回值包含 cat1 和 children
    pass
```

### T-002: 保存分类到数据库
```python
def test_save_taxonomy_updates_database():
    """用户确认后，taxonomy表应被更新"""
    # 调用保存接口
    # 验证数据库中的categories_json已更新
    pass
```

### T-003: 取消不保存
```python
def test_cancel_does_not_modify_taxonomy():
    """用户取消时，taxonomy表应保持不变"""
    # 记录原始taxonomy
    # 调用取消操作
    # 验证taxonomy未变
    pass
```

### T-004: LLM返回格式异常
```python
def test_invalid_llm_response_raises_error():
    """LLM返回非JSON格式时应抛出错误"""
    # Mock LLM返回纯文本
    # 验证抛出适当的异常
    pass
```

### T-005: 空岗位名
```python
def test_empty_position_name_returns_400():
    """空岗位名应返回400错误"""
    # 发送空position
    # 验证返回400状态码
    pass
```

### T-006: LLM调用超时
```python
def test_llm_timeout_returns_error():
    """LLM调用超时时应返回超时错误"""
    # Mock LLM超时
    # 验证返回适当的错误信息
    pass
```

## 红-绿-重构循环计划

- [ ] 循环 1: T-001 — 实现LLM生成分类的核心服务函数
- [ ] 循环 2: T-005 — 添加输入验证
- [ ] 循环 3: T-004 — 处理LLM返回格式异常
- [ ] 循环 4: T-006 — 处理LLM调用超时
- [ ] 循环 5: T-002 — 实现保存分类的API端点
- [ ] 循环 6: T-003 — 验证取消不保存（前端逻辑，后端无需额外测试）

## 文件变更计划

### 新增文件
- `backend/app/services/taxonomy_suggest.py` — LLM生成分类建议的服务
- `backend/tests/test_taxonomy_suggest.py` — 测试文件

### 修改文件
- `backend/app/routers/profile.py` — 添加生成/保存API端点
- `frontend/src/components/SettingsPanel.vue` — 添加按钮和预览UI
- `frontend/src/api/index.js` — 添加API调用方法

## 前端交互流程

```
用户点击"AI生成分类"按钮
    ↓
显示loading状态 + 调用后端API
    ↓
后端调用LLM生成分类建议
    ↓
返回分类列表 → 前端展示预览
    ↓
┌─────────────┬─────────────┐
│   采纳       │   取消       │
│   ↓          │   ↓          │
│ 调用保存API  │ 关闭预览     │
│ 覆盖taxonomy │ 不做任何修改  │
└─────────────┴─────────────┘
```
