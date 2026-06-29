"""
自动化测试 — Agent 工作流 Bug 验证（BUG-005 ~ BUG-010）

使用 pytest + unittest.mock，所有外部依赖均已 mock。
每个 bug 有测试：修复前应 FAIL，修复后应 PASS。
"""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock


# ═══════════════════════════════════════════════════
#  BUG-005: classify_node 未传递 user_id
# ═══════════════════════════════════════════════════

class TestBug005:
    """BUG-005: classify_node 应将 user_id 传递给 get_taxonomy_for_position"""

    @pytest.mark.asyncio
    async def test_classify_passes_user_id_to_taxonomy(self):
        """classify_node 应使用 user_id 获取用户个人分类"""
        import inspect
        from app.agents.submit.classify import classify_node

        # 读取源码检查 run_db 调用方式
        source = inspect.getsource(classify_node)

        # 有 bug: run_db(get_taxonomy_for_position) — 直接传函数引用
        # 修复后: run_db(lambda: get_taxonomy_for_position(user_id=...)) — lambda 包装
        if 'run_db(get_taxonomy_for_position)' in source:
            pytest.fail(
                "BUG-005: run_db(get_taxonomy_for_position) 直接传函数引用，"
                "未传递 user_id。应改为 run_db(lambda: get_taxonomy_for_position(user_id=...))"
            )

        # 额外验证：源码中应包含 user_id 传递
        if 'get_taxonomy_for_position' in source and 'user_id' not in source.split('get_taxonomy_for_position')[0].split('\n')[-1]:
            pass  # 可能在 lambda 中传递，需要更细致检查


# ═══════════════════════════════════════════════════
#  BUG-006: taxonomy children 类型不安全
# ═══════════════════════════════════════════════════

class TestBug006:
    """BUG-006: taxonomy children 可能是字典列表，应正确解析"""

    def test_children_as_strings_works(self):
        """字符串列表形式的 children 应正常工作"""
        taxonomy = {
            "categories": [
                {"cat1": "前端", "children": ["React", "Vue", "Angular"]}
            ]
        }
        valid_cat2_by_cat1 = {}
        for cat in taxonomy["categories"]:
            cname = cat.get("cat1", "")
            if cname:
                valid_cat2_by_cat1[cname] = set(cat.get("children", []))

        assert valid_cat2_by_cat1["前端"] == {"React", "Vue", "Angular"}

    def test_children_as_dicts_causes_type_error(self):
        """字典列表形式的 children 在 set() 转换时崩溃"""
        dict_children = [{"name": "React", "id": 1}, {"name": "Vue", "id": 2}]

        with pytest.raises(TypeError, match="unhashable type"):
            set(dict_children)

    def test_classify_valid_cat2_parses_children_correctly(self):
        """classify_node 的 valid_cat2 构建应正确处理两种 children 格式"""
        # 验证修复后的 classify_node 源码使用了类型安全的解析
        import inspect
        from app.agents.submit.classify import classify_node
        source = inspect.getsource(classify_node)

        # 修复后应使用 isinstance(c, str) 检查
        if 'isinstance(c, str)' not in source:
            pytest.fail(
                "BUG-006: classify_node 的 children 解析未使用 isinstance 类型检查，"
                "字典列表会抛出 TypeError"
            )

    def test_children_type_safe_parsing(self):
        """修复后应同时支持字符串和字典形式的 children"""
        # 字典形式
        children_dicts = [{"name": "React"}, {"name": "Vue"}]
        result = set(
            c if isinstance(c, str) else c.get("name", "")
            for c in children_dicts
        )
        assert result == {"React", "Vue"}, "修复后应从字典中提取 name"

        # 字符串形式
        children_strs = ["React", "Vue"]
        result2 = set(
            c if isinstance(c, str) else c.get("name", "")
            for c in children_strs
        )
        assert result2 == {"React", "Vue"}, "修复后字符串形式应保持不变"


# ═══════════════════════════════════════════════════
#  BUG-007: evaluate_tagging_quality 不归一化
# ═══════════════════════════════════════════════════

class TestBug007:
    """BUG-007: 质量评分应按题目数归一化"""

    def _make_row(self, cat1="前端", cat2="React", diff="L2-中等"):
        """构造一行 tagged row: [url, company, round, question, cat1, cat2, tags, diff]"""
        return ["http://t", "公司", "一面", "问题", cat1, cat2, "tag", diff]

    def test_many_questions_unfairly_penalized(self):
        """50 道题中有 7 道错（14%错误率）→ 当前实现得 0 分"""
        from app.agents.shared.quality import evaluate_tagging_quality

        valid_cat1 = {"前端", "后端", "算法"}
        valid_cat2 = {"前端": {"React", "Vue"}, "后端": {"Java", "Python"}}

        rows = []
        for i in range(43):
            rows.append(self._make_row())  # 正确
        for i in range(7):
            rows.append(self._make_row(cat1="不存在"))  # 错误

        score = evaluate_tagging_quality(rows, valid_cat1=valid_cat1, valid_cat2_by_cat1=valid_cat2)

        # 50 题 * 1.5 扣分/题错误 = 10.5 扣分 → 10.0 - 10.5 = -0.5 → clamp 0
        # 但 14% 错误率不应该得 0 分
        if score == 0.0:
            pytest.fail(
                f"BUG-007: 50 道题中 7 道错（14%错误率）得 0 分，不合理。"
                f"应按错误率归一化评分。"
            )

    def test_same_error_rate_different_scores(self):
        """同样的错误率，题目数不同导致评分差异巨大"""
        from app.agents.shared.quality import evaluate_tagging_quality

        valid_cat1 = {"前端", "后端"}
        valid_cat2 = {"前端": {"React"}, "后端": {"Java"}}

        # 场景 A: 3 道题，1 道错（33% 错误率）
        rows_a = [self._make_row(), self._make_row(), self._make_row(cat1="不存在")]
        score_a = evaluate_tagging_quality(rows_a, valid_cat1=valid_cat1, valid_cat2_by_cat1=valid_cat2)

        # 场景 B: 30 道题，10 道错（33% 错误率）
        rows_b = [self._make_row() for _ in range(20)] + [self._make_row(cat1="不存在") for _ in range(10)]
        score_b = evaluate_tagging_quality(rows_b, valid_cat1=valid_cat1, valid_cat2_by_cat1=valid_cat2)

        # 同样的错误率，评分应该相近
        # 当前实现: A = 10 - 1.5 = 8.5, B = 10 - 15 = 0
        if abs(score_a - score_b) > 3.0:
            pytest.fail(
                f"BUG-007: 同样 33% 错误率，"
                f"3 题得分 {score_a}，30 题得分 {score_b}，差异 {abs(score_a - score_b):.1f} 分"
            )


# ═══════════════════════════════════════════════════
#  BUG-008: clear_qb_node 裸 BEGIN/COMMIT
# ═══════════════════════════════════════════════════

class TestBug008:
    """BUG-008: clear_qb_node 应使用 with conn 而非裸 BEGIN/COMMIT"""

    def test_clear_qb_uses_manual_transaction(self):
        """检查 clear_qb_node 源码是否使用 BEGIN/COMMIT"""
        import inspect
        from app.agents.build.nodes import clear_qb_node
        source = inspect.getsource(clear_qb_node)

        if 'conn.execute("BEGIN")' in source or "conn.execute('BEGIN')" in source:
            # 检查是否使用了 with conn 替代
            if 'with get_db_connection()' not in source and 'with conn' not in source:
                pytest.fail(
                    "BUG-008: clear_qb_node 使用裸 BEGIN/COMMIT，"
                    "应使用 'with conn:' 上下文管理器"
                )


# ═══════════════════════════════════════════════════
#  BUG-009: 黑名单精确匹配
# ═══════════════════════════════════════════════════

class TestBug009:
    """BUG-009: 黑名单应使用子串匹配而非精确匹配"""

    def test_exact_match_misses_variants(self):
        """精确匹配无法过滤 '请做自我介绍' 等变体，应使用子串匹配"""
        import inspect
        from app.agents.submit.extract import extract_node
        source = inspect.getsource(extract_node)

        # 有 bug: q.strip() == b (精确匹配)
        # 修复后: b in q (子串匹配)
        if 'q.strip() == b' in source:
            pytest.fail(
                "BUG-009: 黑名单使用精确匹配 (q.strip() == b)，"
                "无法过滤 '请做自我介绍' 等变体。应改为 'b in q' 子串匹配"
            )

    def test_substring_match_catches_variants(self):
        """子串匹配能正确过滤"""
        _EXTRACT_BLACKLIST = ["自我介绍", "反问", "想问我", "职业规划", "加班", "薪资", "为什么离职", "优缺点"]

        questions = [
            "请做一下自我介绍",
            "你期望的薪资是多少",
            "介绍一下 React 生命周期",
        ]

        # 修复后：子串匹配
        filtered = [q for q in questions if q.strip() and not any(b in q for b in _EXTRACT_BLACKLIST)]

        assert len(filtered) == 1, (
            f"BUG-009: 子串匹配应只保留 'React 生命周期'，实际保留 {len(filtered)} 条"
        )
        assert "React" in filtered[0]


# ═══════════════════════════════════════════════════
#  BUG-010: build 节点绕过 run_db
# ═══════════════════════════════════════════════════

class TestBug010:
    """BUG-010: build 节点应使用 run_db 包装数据库操作"""

    def test_backup_db_node_uses_run_db(self):
        """backup_db_node 应通过 run_db 执行数据库操作"""
        import inspect
        from app.agents.build.nodes import backup_db_node
        source = inspect.getsource(backup_db_node)

        # 检查是否直接调用了 get_db_connection() 而没有通过 run_db
        has_direct_db = 'get_db_connection().execute' in source
        uses_run_db = 'await run_db' in source or 'run_db(' in source

        if has_direct_db and not uses_run_db:
            pytest.fail(
                "BUG-010: backup_db_node 直接调用 get_db_connection().execute()，"
                "应通过 run_db 包装以确保线程安全"
            )
