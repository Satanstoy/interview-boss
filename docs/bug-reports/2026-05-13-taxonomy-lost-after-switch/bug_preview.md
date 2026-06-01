# Bug 预览报告

**日期:** 2026-05-13
**问题:** 采纳AI分类后切换岗位再返回或点击"保存全局配置"，分类丢失
**严重程度:** Critical

## 初步诊断

### 问题现象
1. 用户采纳AI生成的分类后，分类显示正确
2. 切换到其他岗位再切换回原岗位，采纳的分类丢失
3. 点击"保存全局配置"按钮，AI推荐的分类丢失

### 根本原因

**BUG-001: get_taxonomy_for_position 查询不精确**
`get_taxonomy_for_position` 函数查询 taxonomy 表时只按 `position_name` 过滤，不区分 `source` 和 `owner_id`。当同一岗位有多个分类记录（系统默认 + 用户个人）时，返回结果不确定。

**BUG-002: confirm_taxonomy 保存到系统分类而非用户个人分类**
`confirm_taxonomy` 端点调用 `save_taxonomy_suggestion(position, categories)` 时使用默认参数 `source='system'` 和 `owner_id=None`，导致AI采纳的分类保存到系统分类而非用户个人分类。

**BUG-003: update_profile 保存全局配置时未保存为用户个人分类**
`update_profile` 端点调用 `save_taxonomy_for_position(position, tc["categories"])` 时未传递 `source='user'` 和 `owner_id`，导致分类被保存为系统分类。

**BUG-004: get_profile 未传递 user_id 导致无法加载用户个人分类**
管理员的 `get_profile` 端点调用 `get_taxonomy_for_position(current_pos)` 时未传递 `user_id`，导致无法查找到用户个人分类，总是返回系统分类。

### 影响范围
- **功能:** AI分类采纳后无法持久化，保存全局配置也会丢失分类
- **用户:** 所有用户（特别是管理员）
- **数据:** 分类数据可能被覆盖

## 风险评估

| 风险类型 | 等级 | 说明 |
|---------|------|------|
| 功能中断 | Critical | AI分类采纳和保存功能不可靠 |
| 数据完整性 | High | 分类数据可能被错误覆盖 |
| 安全风险 | Low | 无安全风险 |
